#!/usr/bin/env node

// ============================================================================
// Follow Builders — Prepare Digest
// ============================================================================
// Gathers everything the LLM needs to produce a digest:
// - Fetches the central feeds (tweets + podcasts)
// - Fetches the latest prompts from GitHub
// - Reads the user's config (language, delivery method)
// - Outputs a single JSON blob to stdout
//
// The LLM's ONLY job is to read this JSON, remix the content, and output
// the digest text. Everything else is handled here deterministically.
//
// Usage: node prepare-digest.js
// Output: JSON to stdout
// ============================================================================

import { readFile, mkdir, writeFile } from 'fs/promises';
import { existsSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

// -- Constants ---------------------------------------------------------------

const USER_DIR = join(homedir(), '.follow-builders');
const CONFIG_PATH = join(USER_DIR, 'config.json');
const CACHE_DIR = join(USER_DIR, 'cache');
const CACHE_PATHS = {
  x: join(CACHE_DIR, 'feed-x.json'),
  podcasts: join(CACHE_DIR, 'feed-podcasts.json'),
  blogs: join(CACHE_DIR, 'feed-blogs.json')
};

const FEED_X_URL = 'https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-x.json';
const FEED_PODCASTS_URL = 'https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-podcasts.json';
const FEED_BLOGS_URL = 'https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-blogs.json';

const PROMPTS_BASE = 'https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/prompts';
const PROMPT_FILES = [
  'summarize-podcast.md',
  'summarize-tweets.md',
  'summarize-blogs.md',
  'digest-intro.md',
  'translate.md'
];

const FETCH_TIMEOUT_MS = 15000;
const FETCH_RETRIES = 3;

// -- Fetch helpers -----------------------------------------------------------

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function normalizeError(err) {
  if (!err) return 'unknown error';
  if (typeof err === 'string') return err;
  if (err.name === 'AbortError') return `timeout after ${FETCH_TIMEOUT_MS}ms`;
  return err.message || String(err);
}

async function fetchWithRetry(url, parser) {
  let lastError = null;

  for (let attempt = 1; attempt <= FETCH_RETRIES; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

    try {
      const res = await fetch(url, {
        signal: controller.signal,
        headers: { 'user-agent': 'follow-builders/1.0' }
      });

      if (!res.ok) {
        lastError = `HTTP ${res.status} for ${url}`;
      } else {
        const data = parser === 'json' ? await res.json() : await res.text();
        return { data, error: null, attempts: attempt };
      }
    } catch (err) {
      lastError = normalizeError(err);
    } finally {
      clearTimeout(timeout);
    }

    if (attempt < FETCH_RETRIES) {
      await sleep(attempt * 750);
    }
  }

  return { data: null, error: lastError, attempts: FETCH_RETRIES };
}

async function fetchJSON(url) {
  return fetchWithRetry(url, 'json');
}

async function fetchText(url) {
  return fetchWithRetry(url, 'text');
}

async function writeJSONSnapshot(path, payload) {
  try {
    await mkdir(CACHE_DIR, { recursive: true });
    await writeFile(path, JSON.stringify(payload, null, 2));
    return null;
  } catch (err) {
    return normalizeError(err);
  }
}

async function readJSONSnapshot(path) {
  if (!existsSync(path)) return { data: null, error: 'snapshot missing' };

  try {
    return {
      data: JSON.parse(await readFile(path, 'utf-8')),
      error: null
    };
  } catch (err) {
    return { data: null, error: normalizeError(err) };
  }
}

function getFeedItems(kind, payload) {
  if (!payload) return [];

  switch (kind) {
    case 'x':
      return payload.x || [];
    case 'podcasts':
      return payload.podcasts || [];
    case 'blogs':
      return payload.blogs || [];
    default:
      return [];
  }
}

async function loadFeed(kind, url, snapshotPath, errors) {
  const live = await fetchJSON(url);

  if (live.data) {
    const snapshotWriteError = await writeJSONSnapshot(snapshotPath, live.data);
    if (snapshotWriteError) {
      errors.push(`Could not write ${kind} snapshot: ${snapshotWriteError}`);
    }

    return {
      data: live.data,
      source: 'live',
      snapshotPath,
      liveAttempts: live.attempts
    };
  }

  errors.push(`Could not fetch ${kind} feed: ${live.error}`);

  const snapshot = await readJSONSnapshot(snapshotPath);
  if (snapshot.data) {
    return {
      data: snapshot.data,
      source: 'snapshot',
      snapshotPath,
      liveAttempts: live.attempts,
      snapshotGeneratedAt: snapshot.data.generatedAt || null
    };
  }

  errors.push(`Could not load ${kind} snapshot: ${snapshot.error}`);

  return {
    data: null,
    source: 'missing',
    snapshotPath,
    liveAttempts: live.attempts,
    snapshotGeneratedAt: null
  };
}

// -- Main --------------------------------------------------------------------

async function main() {
  const errors = [];

  // 1. Read user config
  let config = {
    language: 'en',
    frequency: 'daily',
    delivery: { method: 'stdout' }
  };
  if (existsSync(CONFIG_PATH)) {
    try {
      config = JSON.parse(await readFile(CONFIG_PATH, 'utf-8'));
    } catch (err) {
      errors.push(`Could not read config: ${err.message}`);
    }
  }

  // 2. Fetch the feeds with retries, then fall back to local snapshots if needed
  const [xResult, podcastsResult, blogsResult] = await Promise.all([
    loadFeed('x', FEED_X_URL, CACHE_PATHS.x, errors),
    loadFeed('podcasts', FEED_PODCASTS_URL, CACHE_PATHS.podcasts, errors),
    loadFeed('blogs', FEED_BLOGS_URL, CACHE_PATHS.blogs, errors)
  ]);

  const feedX = xResult.data;
  const feedPodcasts = podcastsResult.data;
  const feedBlogs = blogsResult.data;

  // 3. Load prompts with priority: user custom > remote (GitHub) > local default
  //
  // If the user has a custom prompt at ~/.follow-builders/prompts/<file>,
  // use that (they personalized it — don't overwrite with remote updates).
  // Otherwise, fetch the latest from GitHub so they get central improvements.
  // If GitHub is unreachable, fall back to the local copy shipped with the skill.
  const prompts = {};
  const scriptDir = decodeURIComponent(new URL('.', import.meta.url).pathname);
  const localPromptsDir = join(scriptDir, '..', 'prompts');
  const userPromptsDir = join(USER_DIR, 'prompts');

  for (const filename of PROMPT_FILES) {
    const key = filename.replace('.md', '').replace(/-/g, '_');
    const userPath = join(userPromptsDir, filename);
    const localPath = join(localPromptsDir, filename);

    // Priority 1: user's custom prompt (they personalized it)
    if (existsSync(userPath)) {
      prompts[key] = await readFile(userPath, 'utf-8');
      continue;
    }

    // Priority 2: latest from GitHub (central updates)
    const remote = await fetchText(`${PROMPTS_BASE}/${filename}`);
    if (remote.data) {
      prompts[key] = remote.data;
      continue;
    }

    if (remote.error) {
      errors.push(`Could not fetch prompt ${filename}: ${remote.error}`);
    }

    // Priority 3: local copy shipped with the skill
    if (existsSync(localPath)) {
      prompts[key] = await readFile(localPath, 'utf-8');
    } else {
      errors.push(`Could not load prompt: ${filename}`);
    }
  }

  const sources = {
    x: xResult.source,
    podcasts: podcastsResult.source,
    blogs: blogsResult.source
  };
  const contentSource = Object.values(sources).every(source => source === 'live')
    ? 'live'
    : Object.values(sources).every(source => source === 'snapshot' || source === 'missing')
      ? 'snapshot'
      : 'mixed';
  const stats = {
    podcastEpisodes: feedPodcasts?.podcasts?.length || 0,
    xBuilders: feedX?.x?.length || 0,
    totalTweets: (feedX?.x || []).reduce((sum, a) => sum + a.tweets.length, 0),
    blogPosts: feedBlogs?.blogs?.length || 0,
    feedGeneratedAt: feedX?.generatedAt || feedPodcasts?.generatedAt || feedBlogs?.generatedAt || null
  };
  const hasUsableContent = stats.podcastEpisodes > 0 || stats.xBuilders > 0 || stats.blogPosts > 0;

  // 4. Build the output — everything the LLM needs in one blob
  const output = {
    status: hasUsableContent ? 'ok' : 'empty',
    generatedAt: new Date().toISOString(),

    // User preferences
    config: {
      language: config.language || 'en',
      frequency: config.frequency || 'daily',
      delivery: config.delivery || { method: 'stdout' }
    },

    // Content to remix
    podcasts: feedPodcasts?.podcasts || [],
    x: feedX?.x || [],
    blogs: feedBlogs?.blogs || [],

    // Stats for the LLM to reference
    stats,
    hasUsableContent,
    contentSource,
    sources,
    snapshots: {
      x: {
        path: CACHE_PATHS.x,
        generatedAt: xResult.snapshotGeneratedAt || feedX?.generatedAt || null
      },
      podcasts: {
        path: CACHE_PATHS.podcasts,
        generatedAt: podcastsResult.snapshotGeneratedAt || feedPodcasts?.generatedAt || null
      },
      blogs: {
        path: CACHE_PATHS.blogs,
        generatedAt: blogsResult.snapshotGeneratedAt || feedBlogs?.generatedAt || null
      }
    },

    // Prompts — the LLM reads these and follows the instructions
    prompts,

    // Non-fatal errors
    errors: errors.length > 0 ? errors : undefined
  };

  console.log(JSON.stringify(output, null, 2));
}

main().catch(err => {
  console.error(JSON.stringify({
    status: 'error',
    message: err.message
  }));
  process.exit(1);
});
