#!/bin/sh
# Checksum-verified start of the llama.cpp model server (EA-24; ADR-001 §3.6 and §11).
#
# 1. Downloads $LLM_MODEL_URL to $MODEL_DIR/$LLM_MODEL_FILE when the file is missing (through a
#    .partial file, so an interrupted download is never taken for a model).
# 2. Refuses to start when the file's sha256 differs from $LLM_MODEL_SHA256 (the file is kept, for
#    inspection).
# 3. Serves the model as "$LLM_ALIAS@sha256-<first 12 hex of the file's ACTUAL sha256>": the id the
#    Model Gateway finds in GET /v1/models proves which file runs, so a newer build can never be
#    called in place of a pinned one (D18).
#
# LLM_SERVER_ARGS (optional) replaces the default server flags "-c 8192 -t 6 --jinja"; the embedding
# service (EA-35) uses it for "--embeddings --pooling cls ...".
#
# MODEL_DIR and LLAMA_SERVER_BIN exist for scripts/checks/model-start.test.mjs.
set -eu

model_dir="${MODEL_DIR:-/models}"
server="${LLAMA_SERVER_BIN:-/app/llama-server}"
: "${LLM_MODEL_FILE:?LLM_MODEL_FILE is required}"
: "${LLM_MODEL_URL:?LLM_MODEL_URL is required}"
: "${LLM_MODEL_SHA256:?LLM_MODEL_SHA256 is required}"
: "${LLM_ALIAS:?LLM_ALIAS is required}"
server_args="${LLM_SERVER_ARGS:--c 8192 -t 6 --jinja}"

file="$model_dir/$LLM_MODEL_FILE"
if [ ! -f "$file" ]; then
  echo "model file $LLM_MODEL_FILE missing: downloading it" >&2
  curl -fL --retry 3 -o "$file.partial" "$LLM_MODEL_URL"
  mv "$file.partial" "$file"
fi

actual=$(sha256sum "$file" | cut -d' ' -f1)
if [ "$actual" != "$LLM_MODEL_SHA256" ]; then
  echo "model file sha256 mismatch: expected $LLM_MODEL_SHA256, got $actual" >&2
  exit 1
fi

served="$LLM_ALIAS@sha256-$(printf %s "$actual" | cut -c1-12)"
echo "model file sha256 verified; serving $served" >&2
# $server_args is word-split on purpose: it is a list of flags.
exec "$server" -m "$file" --alias "$served" --host 0.0.0.0 --port 8080 $server_args
