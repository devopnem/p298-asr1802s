# Building Like CI Locally

CI runs inside `ghcr.io/openwrt/tools:latest` (Ubuntu 24.04, ~1.5 GB image).
You have three options: distrobox, podman, or native Void Linux.

---

## Option A: distrobox (recommended — easiest)

distrobox creates a persistent container that feels like a native shell.

```sh
# Create once (~1.5 GB download)
distrobox create --name openwrt-ci --image ghcr.io/openwrt/tools:latest
distrobox enter openwrt-ci

# Inside the distrobox — build
cd /home/void/Downloads/Modems/Notion_R291_ASR1802S_P298_N13/openwrt-fork
rm -rf .config build_dir staging_dir
cat >> .config <<'EOF'
CONFIG_DEVEL=y
CONFIG_AUTOREMOVE=y
CONFIG_TARGET_asr1802s=y
CONFIG_TARGET_asr1802s_generic=y
CONFIG_KERNEL_WERROR=y
CONFIG_ALL_KMODS=y
EOF
make defconfig
make tools/install -j$(nproc) BUILD_LOG=1
make toolchain/install -j$(nproc) BUILD_LOG=1
make target/compile -j$(nproc) BUILD_LOG=1
make package/linux/compile -j$(nproc) BUILD_LOG=1
```

The repo at `openwrt-fork/` is shared — edits on Void appear inside distrobox.

## Option B: podman (same as Docker but rootless)

```sh
podman pull ghcr.io/openwrt/tools:latest

podman run -it --rm \
  --privileged --pid=host \
  -v /home/void/Downloads/Modems/Notion_R291_ASR1802S_P298_N13/openwrt-fork:/work \
  -w /work \
  ghcr.io/openwrt/tools:latest \
  bash
```

Then same build commands as above inside the container.

### One-liner (full build)

```sh
podman run -it --rm --privileged --pid=host \
  -v $(pwd)/openwrt-fork:/work -w /work \
  ghcr.io/openwrt/tools:latest bash -c \
  'rm -rf .config && printf "CONFIG_DEVEL=y\nCONFIG_AUTOREMOVE=y\nCONFIG_TARGET_asr1802s=y\nCONFIG_TARGET_asr1802s_generic=y\nCONFIG_KERNEL_WERROR=y\nCONFIG_ALL_KMODS=y\n" > .config && make defconfig && make tools/install -j$(nproc) BUILD_LOG=1 && make toolchain/install -j$(nproc) BUILD_LOG=1 && make target/compile -j$(nproc) BUILD_LOG=1 && make package/linux/compile -j$(nproc) BUILD_LOG=1 && echo "BUILD OK"'
```

## Option C: Native Void Linux build

OpenWrt can build natively on Void Linux (musl). Your system already has
gcc, g++, make, flex, bison, gawk, git, perl, python3, rsync, wget, unzip.

### Install missing deps

```sh
sudo xbps-install -S patchelf ncurses-devel libssl-devel
```

### Build

```sh
cd openwrt-fork
rm -rf .config build_dir staging_dir
cat >> .config <<'EOF'
CONFIG_DEVEL=y
CONFIG_AUTOREMOVE=y
CONFIG_TARGET_asr1802s=y
CONFIG_TARGET_asr1802s_generic=y
CONFIG_KERNEL_WERROR=y
CONFIG_ALL_KMODS=y
EOF
make defconfig
make tools/install -j$(nproc) BUILD_LOG=1
make toolchain/install -j$(nproc) BUILD_LOG=1
make target/compile -j$(nproc) BUILD_LOG=1
make package/linux/compile -j$(nproc) BUILD_LOG=1
```

### Known issue: musl host builds

Void uses musl for the host. OpenWrt host tools sometimes assume glibc.
If you see `symbol not found` errors from host tools, the distrobox/podman
option is more reliable since the CI container is Ubuntu (glibc).

---

## Fast iteration (skip tools/toolchain)

After the first successful build, tools and toolchain are cached in
`staging_dir/`. On subsequent runs:

```sh
# Only rebuild kernel + kmods + DTBs (~5-10 min)
make target/compile -j$(nproc) BUILD_LOG=1
make package/linux/compile -j$(nproc) BUILD_LOG=1
make target/linux/dtb -j$(nproc) BUILD_LOG=1
```

## Verbose build (debug failures)

```sh
make target/compile -j1 V=s BUILD_LOG=1
# Error log: logs/target/linux/compile.txt
```

## CI error dumper

```sh
curl -o .github/workflows/scripts/show_build_failures.sh \
  https://raw.githubusercontent.com/openwrt/openwrt/main/.github/workflows/scripts/show_build_failures.sh
chmod +x .github/workflows/scripts/show_build_failures.sh

make target/compile -j$(nproc) BUILD_LOG=1 || \
  ret=$? .github/workflows/scripts/show_build_failures.sh
```

## ccache (speeds up rebuilds)

```sh
echo CONFIG_CCACHE=y >> .config
make defconfig
# Subsequent builds ~3-5x faster
```
