// SPDX-License-Identifier: GPL-2.0
/*
 * Userspace loader for the hotset_protect cache_ext policy.
 *
 * Modelled line-for-line on policies/cache_ext_fifo.c and
 * policies/cache_ext_s3fifo.c from the cache_ext artifact:
 *   argp options -> validate watch_dir -> open cgroup fd ->
 *   skel__open -> set rodata -> skel__load -> initialize_watch_dir_map ->
 *   bpf_map__attach_cache_ext_ops(map, cgroup_fd) -> skel__attach ->
 *   block on getchar() until SIGINT.
 *
 * Two deltas from upstream:
 *
 *   1. --hot_chunks FILE populates the `hot_chunks` map before attach. The
 *      file is produced by load_hotset.py from a Tier-1d result JSON; its
 *      format is one chunk per line
 *
 *          <ino:%llu> <chunk:%llu> <bitmap:%llx>
 *
 *      with '#' comment lines. Extent -> chunk-bitmap expansion happens in
 *      Python (numpy) so that this file needs no JSON parser, matching the
 *      dependency-free style of dir_watcher.h.
 *
 *      Passing no --hot_chunks (or an empty table) yields a pure two-list
 *      FIFO with everything cold: that is the CONTROL arm for
 *      bench_mmap_visibility.sh.
 *
 *   2. The `hotset_stats` map is pinned at
 *      /sys/fs/bpf/cache_ext/hotset_stats and the `hot_chunks` map at
 *      /sys/fs/bpf/cache_ext/hotset_chunks, so a shell script can sample the
 *      hook counters with `bpftool map dump pinned ...` while the benchmark
 *      runs, and so the hot table can be REWRITTEN under a live policy.
 *      cache_ext_get_scan.c pins its scan_pids map the same way.
 *
 *   3. --refresh_chunks FILE is a second, non-attaching mode of the same
 *      binary: it bpf_obj_get()s the pinned hot_chunks map of an ALREADY
 *      RUNNING loader, replaces its contents from FILE, and exits. It exists
 *      for test situation E8 (live table refresh mid-benchmark). It is in
 *      this binary rather than a new one because it must reuse
 *      load_hot_chunks() verbatim -- the refreshed table has to be
 *      byte-for-byte what the attach path would have loaded -- and because
 *      `bpftool map update` would need one process spawn per chunk (tens of
 *      thousands, i.e. minutes of stall in the middle of a measured pass).
 *      Upstream ships no refresh idiom; the closest is cache_ext_get_scan.c's
 *      pin-then-poke-from-userspace pattern, which this follows.
 *
 * NOT COMPILED OR RUN ANYWHERE YET: there is no cache_ext kernel and no
 * clang/bpftool in the dev container. Correctness is claimed only against
 * upstream's source idioms.
 */
#include <argp.h>
#include <bpf/bpf.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include <bpf/libbpf.h>

#include "dir_watcher.h"
#include "hotset_protect.skel.h"

#define HOTSET_STATS_PIN "/sys/fs/bpf/cache_ext/hotset_stats"
#define HOTSET_CHUNKS_PIN "/sys/fs/bpf/cache_ext/hotset_chunks"

char *USAGE =
	"Usage: ./hotset_protect --watch_dir <dir> --cgroup_path <path> "
	"[--hot_chunks <file>]\n"
	"       ./hotset_protect --refresh_chunks <file> [--chunks_pin <path>] "
	"[--no_clear]\n";

struct cmdline_args {
	char *watch_dir;
	char *cgroup_path;
	char *hot_chunks;
	char *refresh_chunks;
	char *chunks_pin;
	bool no_clear;
};

/* Must match struct hot_chunk_key in hotset_protect.bpf.c. */
struct hot_chunk_key {
	__u64 ino;
	__u64 chunk;
};

static struct argp_option options[] = {
	{ "watch_dir", 'w', "DIR", 0, "Directory to watch" },
	{ "cgroup_path", 'c', "PATH", 0,
	  "Path to cgroup (e.g., /sys/fs/cgroup/cache_ext_test)" },
	{ "hot_chunks", 'H', "FILE", 0,
	  "Hot-extent chunk table from load_hotset.py (optional)" },
	{ "refresh_chunks", 'R', "FILE", 0,
	  "Refresh mode: rewrite the pinned hot_chunks map from FILE and exit" },
	{ "chunks_pin", 'P', "PATH", 0,
	  "Pin path for the hot_chunks map (default " HOTSET_CHUNKS_PIN ")" },
	{ "no_clear", 'N', NULL, 0,
	  "Refresh mode: merge into the existing table instead of replacing it" },
	{ 0 },
};

static volatile sig_atomic_t exiting;

static void sig_handler(int signo)
{
	exiting = 1;
}

static error_t parse_opt(int key, char *arg, struct argp_state *state)
{
	struct cmdline_args *args = state->input;

	switch (key) {
	case 'w':
		args->watch_dir = arg;
		break;
	case 'c':
		args->cgroup_path = arg;
		break;
	case 'H':
		args->hot_chunks = arg;
		break;
	case 'R':
		args->refresh_chunks = arg;
		break;
	case 'P':
		args->chunks_pin = arg;
		break;
	case 'N':
		args->no_clear = true;
		break;
	default:
		return ARGP_ERR_UNKNOWN;
	}
	return 0;
}

static int parse_args(int argc, char **argv, struct cmdline_args *args)
{
	struct argp argp = { options, parse_opt, 0, 0 };

	argp_parse(&argp, argc, argv, 0, 0, args);

	if (args->chunks_pin == NULL)
		args->chunks_pin = HOTSET_CHUNKS_PIN;

	/*
	 * Refresh mode attaches nothing and creates no cgroup, so it needs
	 * neither watch_dir nor cgroup_path; requiring them would force the
	 * benchmark to repeat arguments that are already implied by the pin.
	 */
	if (args->refresh_chunks != NULL)
		return 0;

	if (args->watch_dir == NULL) {
		fprintf(stderr, "Missing required argument: watch_dir\n%s", USAGE);
		return 1;
	}

	if (args->cgroup_path == NULL) {
		fprintf(stderr, "Missing required argument: cgroup_path\n%s", USAGE);
		return 1;
	}

	return 0;
}

/* Copied verbatim from cache_ext_fifo.c. */
static int validate_watch_dir(const char *watch_dir, char *watch_dir_full_path)
{
	if (access(watch_dir, F_OK) == -1) {
		fprintf(stderr, "Directory does not exist: %s\n", watch_dir);
		return 1;
	}

	if (realpath(watch_dir, watch_dir_full_path) == NULL) {
		perror("realpath");
		return 1;
	}

	/* BPF policy restriction (BPF_PATH_MAX in dir_watcher.bpf.h). */
	if (strlen(watch_dir_full_path) > 128) {
		fprintf(stderr, "watch_dir path too long\n");
		return 1;
	}

	return 0;
}

static int load_hot_chunks(const char *path, int map_fd, unsigned long *n_out)
{
	char line[256];
	unsigned long long ino, chunk, bitmap;
	unsigned long n = 0, lineno = 0;
	FILE *fh;

	fh = fopen(path, "r");
	if (!fh) {
		perror("Failed to open hot_chunks file");
		return -1;
	}

	while (fgets(line, sizeof(line), fh)) {
		struct hot_chunk_key key;
		__u64 value;

		lineno++;
		if (line[0] == '#' || line[0] == '\n')
			continue;

		if (sscanf(line, "%llu %llu %llx", &ino, &chunk, &bitmap) != 3) {
			fprintf(stderr, "hot_chunks: malformed line %lu: %s",
				lineno, line);
			fclose(fh);
			return -1;
		}

		key.ino = (__u64)ino;
		key.chunk = (__u64)chunk;
		value = (__u64)bitmap;

		if (bpf_map_update_elem(map_fd, &key, &value, BPF_ANY)) {
			fprintf(stderr,
				"hot_chunks: failed to insert ino=%llu chunk=%llu: %s\n",
				ino, chunk, strerror(errno));
			fclose(fh);
			return -1;
		}
		n++;
	}

	fclose(fh);
	*n_out = n;
	return 0;
}

/*
 * Delete every entry of a hash map. bpf_map_get_next_key() is documented to
 * stay valid when the key handed in is deleted afterwards, so the walk is
 * "read next, then delete current" rather than "delete then read next".
 */
static int clear_hot_chunks(int map_fd, unsigned long *n_out)
{
	struct hot_chunk_key key, next;
	unsigned long n = 0;
	bool have = false;

	if (bpf_map_get_next_key(map_fd, NULL, &key))
		goto done;
	have = true;

	while (have) {
		bool has_next = bpf_map_get_next_key(map_fd, &key, &next) == 0;

		if (bpf_map_delete_elem(map_fd, &key) && errno != ENOENT) {
			fprintf(stderr, "refresh: failed to delete ino=%llu "
				"chunk=%llu: %s\n",
				(unsigned long long)key.ino,
				(unsigned long long)key.chunk, strerror(errno));
			return -1;
		}
		n++;

		if (!has_next)
			break;
		key = next;
	}

done:
	*n_out = n;
	return 0;
}

/*
 * Refresh mode. The policy stays attached and keeps serving evictions the
 * whole time; only the hot/cold ORACLE changes. Folios already filed onto the
 * hot or cold list are NOT re-filed -- folio_added is the only place list
 * membership is decided -- so a refresh takes effect for pages faulted in
 * after it, which is exactly the E8 question ("does it re-converge?") and not
 * an instantaneous re-sort. Say so out loud in the log.
 */
static int refresh_hot_chunks(struct cmdline_args *args)
{
	unsigned long n_cleared = 0, n_loaded = 0;
	int map_fd;

	map_fd = bpf_obj_get(args->chunks_pin);
	if (map_fd < 0) {
		fprintf(stderr, "refresh: failed to open pinned map %s: %s\n",
			args->chunks_pin, strerror(errno));
		return 1;
	}

	if (!args->no_clear && clear_hot_chunks(map_fd, &n_cleared)) {
		close(map_fd);
		return 1;
	}

	if (load_hot_chunks(args->refresh_chunks, map_fd, &n_loaded)) {
		close(map_fd);
		return 1;
	}

	fprintf(stderr,
		"hotset_protect: refreshed %s: cleared %lu, loaded %lu from %s "
		"(applies to folios added AFTER this point; already-filed "
		"folios keep their list)\n",
		args->chunks_pin, n_cleared, n_loaded, args->refresh_chunks);

	close(map_fd);
	return 0;
}

int main(int argc, char **argv)
{
	struct cmdline_args args = { 0 };
	struct hotset_protect_bpf *skel = NULL;
	struct bpf_link *link = NULL;
	struct sigaction sa;
	char watch_dir_path[PATH_MAX];
	unsigned long n_chunks = 0;
	bool pinned = false;
	bool chunks_pinned = false;
	int cgroup_fd = -1;
	int ret = 1;

	libbpf_set_strict_mode(LIBBPF_STRICT_ALL);

	if (parse_args(argc, argv, &args))
		return 1;

	if (args.refresh_chunks)
		return refresh_hot_chunks(&args);

	memset(&sa, 0, sizeof(sa));
	sigemptyset(&sa.sa_mask);
	sa.sa_handler = sig_handler;

	if (sigaction(SIGINT, &sa, NULL)) {
		perror("Failed to set up signal handling");
		return 1;
	}

	if (validate_watch_dir(args.watch_dir, watch_dir_path))
		return 1;

	cgroup_fd = open(args.cgroup_path, O_RDONLY);
	if (cgroup_fd < 0) {
		perror("Failed to open cgroup path");
		return 1;
	}

	skel = hotset_protect_bpf__open();
	if (!skel) {
		perror("Failed to open BPF skeleton");
		goto cleanup;
	}

	watch_dir_path_len_map(skel) = strlen(watch_dir_path);
	strcpy(watch_dir_path_map(skel), watch_dir_path);

	if (hotset_protect_bpf__load(skel)) {
		perror("Failed to load BPF skeleton");
		goto cleanup;
	}

	if (initialize_watch_dir_map(watch_dir_path,
				     bpf_map__fd(inode_watchlist_map(skel)), true)) {
		perror("Failed to initialize watch_dir map");
		goto cleanup;
	}

	if (args.hot_chunks) {
		if (load_hot_chunks(args.hot_chunks,
				    bpf_map__fd(skel->maps.hot_chunks),
				    &n_chunks))
			goto cleanup;
		fprintf(stderr, "hotset_protect: loaded %lu hot chunks from %s\n",
			n_chunks, args.hot_chunks);
	} else {
		fprintf(stderr,
			"hotset_protect: no --hot_chunks given; running as "
			"all-cold FIFO control\n");
	}

	/*
	 * Pin the stats map so bench_mmap_visibility.sh can sample the hook
	 * counters from a different process. cache_ext_get_scan.c does the
	 * same for its scan_pids map; note that it also has to mkdir
	 * /sys/fs/bpf/cache_ext beforehand (the run.sh scripts do it).
	 */
	if (bpf_map__pin(skel->maps.hotset_stats, HOTSET_STATS_PIN) < 0) {
		perror("Failed to pin hotset_stats map");
		goto cleanup;
	}
	pinned = true;

	/*
	 * Pin hot_chunks too, so `--refresh_chunks` from a second process can
	 * find it. Pinned unconditionally (even for the empty-table FIFO
	 * control arm), so the bench's teardown is the same in every arm and a
	 * refresh can also be used to LOAD a table into a control run.
	 */
	if (bpf_map__pin(skel->maps.hot_chunks, args.chunks_pin) < 0) {
		perror("Failed to pin hot_chunks map");
		goto cleanup;
	}
	chunks_pinned = true;

	link = bpf_map__attach_cache_ext_ops(skel->maps.hotset_ops, cgroup_fd);
	if (link == NULL) {
		perror("Failed to attach cache_ext_ops to cgroup");
		goto cleanup;
	}

	/* Required for the dir_watcher fexit/vfs_open probe. */
	if (hotset_protect_bpf__attach(skel)) {
		perror("Failed to attach BPF skeleton");
		goto cleanup;
	}

	printf("hotset_protect attached to %s (stats pinned at %s, "
	       "hot_chunks pinned at %s). Press any key to exit...\n",
	       args.cgroup_path, HOTSET_STATS_PIN, args.chunks_pin);
	getchar();
	ret = 0;

cleanup:
	if (chunks_pinned && bpf_map__unpin(skel->maps.hot_chunks, args.chunks_pin) < 0)
		perror("Failed to unpin hot_chunks map");
	if (pinned && bpf_map__unpin(skel->maps.hotset_stats, HOTSET_STATS_PIN) < 0)
		perror("Failed to unpin hotset_stats map");
	if (cgroup_fd >= 0)
		close(cgroup_fd);
	bpf_link__destroy(link);
	hotset_protect_bpf__destroy(skel);
	return ret;
}
