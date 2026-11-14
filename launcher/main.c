/* gestyq.app launcher. Spawns `python app.py` as a child (not exec) so this signed bundle stays the
   "responsible process": macOS then lists Accessibility and Camera access under "gestyq" instead of
   python or the terminal. Paths come from Contents/Resources so rebuilding the code isn't needed
   (a rebuilt binary has a new signature and would lose the Accessibility grant). */
#include <errno.h>
#include <fcntl.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static pid_t child = 0;

static void forward(int sig) { if (child > 0) kill(child, sig); }

static int read_line(const char *path, char *out, size_t n) {
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    if (!fgets(out, (int)n, f)) { fclose(f); return -1; }
    fclose(f);
    out[strcspn(out, "\r\n")] = 0;
    return 0;
}

int main(void) {
    char exe[PATH_MAX], real[PATH_MAX], tmp[PATH_MAX], contents[PATH_MAX], app[PATH_MAX];
    uint32_t n = sizeof exe;
    if (_NSGetExecutablePath(exe, &n) != 0 || !realpath(exe, real)) return 1;
    strlcpy(tmp, real, sizeof tmp);
    strlcpy(contents, dirname(dirname(tmp)), sizeof contents);      /* .../gestyq.app/Contents */
    strlcpy(tmp, contents, sizeof tmp);
    strlcpy(app, dirname(tmp), sizeof app);                          /* .../gestyq.app */

    char dir_file[PATH_MAX], py_file[PATH_MAX], dir[PATH_MAX], py[PATH_MAX], script[PATH_MAX];
    snprintf(dir_file, sizeof dir_file, "%s/Resources/source_dir", contents);
    snprintf(py_file, sizeof py_file, "%s/Resources/python", contents);
    if (read_line(dir_file, dir, sizeof dir) || read_line(py_file, py, sizeof py)) {
        fprintf(stderr, "gestyq: missing Resources/source_dir or Resources/python\n");
        return 1;
    }
    snprintf(script, sizeof script, "%s/app.py", dir);
    if (chdir(dir) != 0) { perror("gestyq: chdir"); return 1; }
    setenv("GESTYQ_APP", app, 1);
    setenv("PYTHONUNBUFFERED", "1", 1);

    /* stdout/stderr -> ~/Library/Logs/gestyq.log */
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    const char *home = getenv("HOME");
    char log[PATH_MAX];
    if (home) {
        snprintf(log, sizeof log, "%s/Library/Logs/gestyq.log", home);
        posix_spawn_file_actions_addopen(&fa, 1, log, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        posix_spawn_file_actions_adddup2(&fa, 1, 2);
    }

    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);
    char *argv[] = {py, script, NULL};
    int err = posix_spawn(&child, py, &fa, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&fa);
    if (err) { fprintf(stderr, "gestyq: spawn %s: %s\n", py, strerror(err)); return 1; }

    int st = 0;
    while (waitpid(child, &st, 0) < 0 && errno == EINTR) {}
    return WIFEXITED(st) ? WEXITSTATUS(st) : 1;
}
