#!/bin/zsh
set -e
python3 /Users/cecilialiu/Documents/Codex/Skills/lark-suite/scripts/lark_suite_manager.py setup
echo
echo "飞书凭据已安全写入 Keychain，可以关闭此窗口并回到 Codex。"
read -r "?按回车关闭..."
