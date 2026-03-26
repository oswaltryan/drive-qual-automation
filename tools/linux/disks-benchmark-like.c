#define _GNU_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/fs.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define MiB (1024.0 * 1024.0)

typedef struct {
  uint64_t offset;
  double value;
} sample_t;

typedef struct {
  double min;
  double avg;
  double max;
} stats_t;

static void die(const char *msg) {
  perror(msg);
  exit(1);
}

static double now_sec(void) {
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
    die("clock_gettime");
  }
  return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static uint64_t now_usec(void) {
  struct timespec ts;
  if (clock_gettime(CLOCK_REALTIME, &ts) != 0) {
    die("clock_gettime");
  }
  return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)ts.tv_nsec / 1000ULL;
}

static uint64_t align_down_u64(uint64_t v, uint64_t a) {
  return v - (v % a);
}

static uint64_t rand_u64(unsigned int *seed) {
  uint64_t a = (uint64_t)rand_r(seed);
  uint64_t b = (uint64_t)rand_r(seed);
  return (a << 31) ^ b;
}

static void read_full(int fd, void *buf, size_t n) {
  size_t done = 0;
  while (done < n) {
    ssize_t r = read(fd, (char *)buf + done, n - done);
    if (r < 0) {
      if (errno == EINTR) {
        continue;
      }
      die("read");
    }
    if (r == 0) {
      fprintf(stderr, "short read on block device\n");
      exit(1);
    }
    done += (size_t)r;
  }
}

static void write_full(int fd, const void *buf, size_t n) {
  size_t done = 0;
  while (done < n) {
    ssize_t w = write(fd, (const char *)buf + done, n - done);
    if (w < 0) {
      if (errno == EINTR) {
        continue;
      }
      die("write");
    }
    done += (size_t)w;
  }
}

static stats_t compute_stats(const sample_t *samples, size_t n) {
  stats_t s = {0.0, 0.0, 0.0};
  if (n == 0) {
    return s;
  }
  s.min = samples[0].value;
  s.max = samples[0].value;
  double sum = 0.0;
  for (size_t i = 0; i < n; i++) {
    if (samples[i].value < s.min) {
      s.min = samples[i].value;
    }
    if (samples[i].value > s.max) {
      s.max = samples[i].value;
    }
    sum += samples[i].value;
  }
  s.avg = sum / (double)n;
  return s;
}

static uint64_t parse_u64(const char *s, const char *name) {
  char *end = NULL;
  errno = 0;
  unsigned long long v = strtoull(s, &end, 10);
  if (errno != 0 || end == s || *end != '\0') {
    fprintf(stderr, "invalid %s: %s\n", name, s);
    exit(1);
  }
  return (uint64_t)v;
}

static void usage(const char *argv0) {
  fprintf(stderr,
          "Usage: %s --device /dev/sdX [options]\n"
          "Options:\n"
          "  --num-samples N         Read/write samples (default: 10)\n"
          "  --num-access-samples N  Access-time samples (default: 100)\n"
          "  --sample-size BYTES     Sample size, aligned to 4096 (default: 2097152)\n"
          "  --access-size BYTES     Access read size, aligned to 4096 (default: 4096)\n"
          "  --read-only             Skip write benchmark\n"
          "  --seed N                RNG seed (default: current time)\n"
          "  --allow-buffered        Fallback if O_DIRECT open fails\n"
          "  --json-out PATH         Write JSON to file\n"
          "  --help\n",
          argv0);
}

int main(int argc, char **argv) {
  const char *device = NULL;
  const char *json_out = NULL;
  uint64_t num_samples = 10;
  uint64_t num_access_samples = 100;
  uint64_t sample_size = 2 * 1024 * 1024;
  uint64_t access_size = 4096;
  bool do_write = true;
  bool allow_buffered = false;
  unsigned int seed = (unsigned int)time(NULL);

  for (int i = 1; i < argc; i++) {
    if (strcmp(argv[i], "--device") == 0 && i + 1 < argc) {
      device = argv[++i];
    } else if (strcmp(argv[i], "--num-samples") == 0 && i + 1 < argc) {
      num_samples = parse_u64(argv[++i], "num-samples");
    } else if (strcmp(argv[i], "--num-access-samples") == 0 && i + 1 < argc) {
      num_access_samples = parse_u64(argv[++i], "num-access-samples");
    } else if (strcmp(argv[i], "--sample-size") == 0 && i + 1 < argc) {
      sample_size = parse_u64(argv[++i], "sample-size");
    } else if (strcmp(argv[i], "--access-size") == 0 && i + 1 < argc) {
      access_size = parse_u64(argv[++i], "access-size");
    } else if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc) {
      seed = (unsigned int)parse_u64(argv[++i], "seed");
    } else if (strcmp(argv[i], "--json-out") == 0 && i + 1 < argc) {
      json_out = argv[++i];
    } else if (strcmp(argv[i], "--read-only") == 0) {
      do_write = false;
    } else if (strcmp(argv[i], "--allow-buffered") == 0) {
      allow_buffered = true;
    } else if (strcmp(argv[i], "--help") == 0) {
      usage(argv[0]);
      return 0;
    } else {
      usage(argv[0]);
      return 1;
    }
  }

  if (device == NULL) {
    usage(argv[0]);
    return 1;
  }
  if (num_samples == 0 || num_access_samples == 0) {
    fprintf(stderr, "sample counts must be > 0\n");
    return 1;
  }
  if ((sample_size % 4096) != 0 || (access_size % 4096) != 0) {
    fprintf(stderr, "sample-size and access-size must be multiples of 4096\n");
    return 1;
  }

  int open_flags = O_RDWR | O_EXCL | O_SYNC | O_DIRECT | O_CLOEXEC;
  int fd = open(device, open_flags);
  bool used_direct = true;
  if (fd < 0 && allow_buffered && errno == EINVAL) {
    open_flags = O_RDWR | O_EXCL | O_SYNC | O_CLOEXEC;
    fd = open(device, open_flags);
    used_direct = false;
  }
  if (fd < 0) {
    die("open");
  }

  uint64_t device_size = 0;
  if (ioctl(fd, BLKGETSIZE64, &device_size) != 0) {
    die("ioctl(BLKGETSIZE64)");
  }

  if (sample_size > device_size || access_size > device_size) {
    fprintf(stderr, "sample sizes exceed device size\n");
    close(fd);
    return 1;
  }

  uint64_t max_rw_off = align_down_u64(device_size - sample_size, 4096);
  uint64_t max_access_off = align_down_u64(device_size - access_size, 4096);

  void *rw_buf = NULL;
  void *access_buf = NULL;
  if (posix_memalign(&rw_buf, 4096, (size_t)sample_size) != 0) {
    fprintf(stderr, "posix_memalign rw_buf failed\n");
    close(fd);
    return 1;
  }
  if (posix_memalign(&access_buf, 4096, (size_t)access_size) != 0) {
    fprintf(stderr, "posix_memalign access_buf failed\n");
    free(rw_buf);
    close(fd);
    return 1;
  }
  sample_t *read_samples = calloc((size_t)num_samples, sizeof(sample_t));
  sample_t *write_samples = calloc((size_t)num_samples, sizeof(sample_t));
  sample_t *access_samples = calloc((size_t)num_access_samples, sizeof(sample_t));
  uint64_t *rw_offsets = calloc((size_t)num_samples, sizeof(uint64_t));
  if (!read_samples || !write_samples || !access_samples || !rw_offsets) {
    fprintf(stderr, "allocation failed\n");
    free(read_samples);
    free(write_samples);
    free(access_samples);
    free(rw_offsets);
    free(rw_buf);
    free(access_buf);
    close(fd);
    return 1;
  }

  for (uint64_t i = 0; i < num_samples; i++) {
    uint64_t off;
    if (i == 0) {
      off = 0;
    } else if (i == 1) {
      off = align_down_u64(device_size / 2, 4096);
      if (off > max_rw_off) {
        off = max_rw_off;
      }
    } else {
      uint64_t r = rand_u64(&seed);
      uint64_t span = max_rw_off + 1;
      uint64_t wrapped = r - (r / span) * span;
      off = align_down_u64(wrapped, 4096);
    }
    rw_offsets[i] = off;
  }

  for (uint64_t i = 0; i < num_samples; i++) {
    uint64_t off = rw_offsets[i];
    if (lseek(fd, (off_t)off, SEEK_SET) < 0) {
      die("lseek(read-warmup)");
    }
    read_full(fd, access_buf, (size_t)access_size);

    if (lseek(fd, (off_t)off, SEEK_SET) < 0) {
      die("lseek(read)");
    }
    double t0 = now_sec();
    read_full(fd, rw_buf, (size_t)sample_size);
    double t1 = now_sec();

    read_samples[i].offset = off;
    read_samples[i].value = ((double)sample_size / MiB) / (t1 - t0);
  }

  if (do_write) {
    for (uint64_t i = 0; i < num_samples; i++) {
      uint64_t off = rw_offsets[i];
      if (lseek(fd, (off_t)off, SEEK_SET) < 0) {
        die("lseek(write-preserve)");
      }
      read_full(fd, rw_buf, (size_t)sample_size);

      if (lseek(fd, (off_t)off, SEEK_SET) < 0) {
        die("lseek(write)");
      }
      double tw0 = now_sec();
      write_full(fd, rw_buf, (size_t)sample_size);
      if (fsync(fd) != 0) {
        die("fsync");
      }
      double tw1 = now_sec();

      write_samples[i].offset = off;
      write_samples[i].value = ((double)sample_size / MiB) / (tw1 - tw0);
    }
  }

  for (uint64_t i = 0; i < num_access_samples; i++) {
    uint64_t r = rand_u64(&seed);
    uint64_t off = align_down_u64(r % (max_access_off + 1), 4096);
    if (lseek(fd, (off_t)off, SEEK_SET) < 0) {
      die("lseek(access)");
    }
    double t0 = now_sec();
    read_full(fd, access_buf, (size_t)access_size);
    double t1 = now_sec();

    access_samples[i].offset = off;
    access_samples[i].value = (t1 - t0) * 1e6;
  }

  close(fd);

  stats_t rs = compute_stats(read_samples, (size_t)num_samples);
  stats_t ws = do_write ? compute_stats(write_samples, (size_t)num_samples) : (stats_t){0.0, 0.0, 0.0};
  stats_t as = compute_stats(access_samples, (size_t)num_access_samples);

  double read_mb_avg = rs.avg * 1.048576;
  double write_mb_avg = do_write ? (ws.avg * 1.048576) : 0.0;
  double access_msec_avg = as.avg / 1000.0;
  char write_mb_avg_str[32];
  if (do_write) {
    snprintf(write_mb_avg_str, sizeof(write_mb_avg_str), "%.2f", write_mb_avg);
  } else {
    strcpy(write_mb_avg_str, "null");
  }

  FILE *out = stdout;
  if (json_out) {
    out = fopen(json_out, "w");
    if (!out) {
      die("fopen(json-out)");
    }
  }

  fprintf(out, "{\n");
  fprintf(out, "  \"version\": 1,\n");
  fprintf(out, "  \"timestamp_usec\": %" PRIu64 ",\n", now_usec());
  fprintf(out, "  \"device\": \"%s\",\n", device);
  fprintf(out, "  \"device_size\": %" PRIu64 ",\n", device_size);
  fprintf(out, "  \"sample_size\": %" PRIu64 ",\n", sample_size);
  fprintf(out, "  \"access_size\": %" PRIu64 ",\n", access_size);
  fprintf(out, "  \"num_samples\": %" PRIu64 ",\n", num_samples);
  fprintf(out, "  \"num_access_samples\": %" PRIu64 ",\n", num_access_samples);
  fprintf(out,
          "  \"open_mode\": \"%s\",\n",
          used_direct ? "O_RDWR|O_EXCL|O_SYNC|O_DIRECT|O_CLOEXEC"
                      : "O_RDWR|O_EXCL|O_SYNC|O_CLOEXEC");
  fprintf(out,
          "  \"gui_average\": {\"read_MB_s\": %.2f, \"write_MB_s\": %s, \"access_msec\": %.2f},\n",
          read_mb_avg,
          write_mb_avg_str,
          access_msec_avg);

  fprintf(out, "  \"read_samples\": [\n");
  for (uint64_t i = 0; i < num_samples; i++) {
    fprintf(out,
            "    {\"offset\": %" PRIu64 ", \"mib_per_sec\": %.3f}%s\n",
            read_samples[i].offset,
            read_samples[i].value,
            (i + 1 == num_samples) ? "" : ",");
  }
  fprintf(out, "  ],\n");

  fprintf(out, "  \"write_samples\": [\n");
  if (do_write) {
    for (uint64_t i = 0; i < num_samples; i++) {
      fprintf(out,
              "    {\"offset\": %" PRIu64 ", \"mib_per_sec\": %.3f}%s\n",
              write_samples[i].offset,
              write_samples[i].value,
              (i + 1 == num_samples) ? "" : ",");
    }
  }
  fprintf(out, "  ],\n");

  fprintf(out, "  \"access_time_samples\": [\n");
  for (uint64_t i = 0; i < num_access_samples; i++) {
    fprintf(out,
            "    {\"offset\": %" PRIu64 ", \"usec\": %.3f, \"msec\": %.3f}%s\n",
            access_samples[i].offset,
            access_samples[i].value,
            access_samples[i].value / 1000.0,
            (i + 1 == num_access_samples) ? "" : ",");
  }
  fprintf(out, "  ],\n");

  fprintf(out, "  \"summary\": {\n");
  fprintf(out,
          "    \"read_mib_per_sec\": {\"min\": %.3f, \"avg\": %.3f, \"max\": %.3f},\n",
          rs.min,
          rs.avg,
          rs.max);
  if (do_write) {
    fprintf(out,
            "    \"write_mib_per_sec\": {\"min\": %.3f, \"avg\": %.3f, \"max\": %.3f},\n",
            ws.min,
            ws.avg,
            ws.max);
  } else {
    fprintf(out, "    \"write_mib_per_sec\": null,\n");
  }
  fprintf(out,
          "    \"access_usec\": {\"min\": %.3f, \"avg\": %.3f, \"max\": %.3f},\n",
          as.min,
          as.avg,
          as.max);
  fprintf(out,
          "    \"access_msec\": {\"min\": %.3f, \"avg\": %.3f, \"max\": %.3f}\n",
          as.min / 1000.0,
          as.avg / 1000.0,
          as.max / 1000.0);
  fprintf(out, "  }\n");
  fprintf(out, "}\n");

  if (json_out) {
    fclose(out);
  }

  free(read_samples);
  free(write_samples);
  free(access_samples);
  free(rw_offsets);
  free(rw_buf);
  free(access_buf);
  return 0;
}
