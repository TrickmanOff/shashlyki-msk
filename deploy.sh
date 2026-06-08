#!/bin/bash
set -e

HOST=vpn-vm
REMOTE_DIR=/root/shashlyki

rsync -av \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.python-version' \
  --exclude='data/' \
  --exclude='.claude/' \
  . "$HOST:$REMOTE_DIR/"

ssh "$HOST" "cd $REMOTE_DIR && docker-compose up -d --build"
