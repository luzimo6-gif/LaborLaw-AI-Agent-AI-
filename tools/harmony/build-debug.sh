#!/bin/sh

set -eu

DEVECO_APP="/Applications/DevEco-Studio.app"
NODE_HOME="$DEVECO_APP/Contents/tools/node"
DEVECO_SDK_HOME="$DEVECO_APP/Contents/sdk"
JAVA_HOME="$DEVECO_APP/Contents/jbr/Contents/Home"
HVIGORW="$DEVECO_APP/Contents/tools/hvigor/bin/hvigorw"

if [ ! -x "$HVIGORW" ]; then
  echo "DevEco Studio 6.1 is not installed at $DEVECO_APP" >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../../harmony-app" && pwd)

cd "$PROJECT_DIR"
env \
  NODE_HOME="$NODE_HOME" \
  DEVECO_SDK_HOME="$DEVECO_SDK_HOME" \
  JAVA_HOME="$JAVA_HOME" \
  "$HVIGORW" assembleHap \
    --mode module \
    -p module=entry@default \
    -p product=default \
    -p buildMode=debug \
    --no-daemon
