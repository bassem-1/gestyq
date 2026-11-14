/* gestyq.app launcher. Embeds Python: this signed binary IS the app's process, so the dock icon, the
   bundle identity (NSBundle.mainBundle), reopen events and the Accessibility / Camera grants all belong
   to "gestyq" (no python child). libpython is linked at build time (see scripts/bundle.sh); PYTHONHOME
   and the source folder come from Contents/Resources so rebuilding is only needed when the python env or
   folder moves (a rebuilt binary has a new signature and loses the Accessibility grant). argv is
   forwarded to app.py, e.g. --background from the login item. */
#include <fcntl.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern int Py_BytesMain(int argc, char **argv);

static int read_line(const char *path, char *out, size_t n) {
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    if (!fgets(out, (int)n, f)) { fclose(f); return -1; }
    fclose(f);
    out[strcspn(out, "\r\n")] = 0;
    return 0;
}

int main(int argc, char **argv) {
    char exe[PATH_MAX], real[PATH_MAX], tmp[PATH_MAX], contents[PATH_MAX], app[PATH_MAX];
    uint32_t n = sizeof exe;
    if (_NSGetExecutablePath(exe, &n) != 0 || !realpath(exe, real)) return 1;
    strlcpy(tmp, real, sizeof tmp);
    strlcpy(contents, dirname(dirname(tmp)), sizeof contents);      /* .../gestyq.app/Contents */
    strlcpy(tmp, contents, sizeof tmp);
    strlcpy(app, dirname(tmp), sizeof app);                          /* .../gestyq.app */

    /* stdout/stderr -> ~/Library/Logs/gestyq.log */
    const char *home = getenv("HOME");
    if (home) {
        char log[PATH_MAX];
        snprintf(log, sizeof log, "%s/Library/Logs/gestyq.log", home);
        int fd = open(log, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd >= 0) { dup2(fd, 1); dup2(fd, 2); if (fd > 2) close(fd); }
    }

    char dir_file[PATH_MAX], home_file[PATH_MAX], dir[PATH_MAX], pyhome[PATH_MAX], script[PATH_MAX];
    snprintf(dir_file, sizeof dir_file, "%s/Resources/source_dir", contents);
    snprintf(home_file, sizeof home_file, "%s/Resources/python_home", contents);
    if (read_line(dir_file, dir, sizeof dir) || read_line(home_file, pyhome, sizeof pyhome)) {
        fprintf(stderr, "gestyq: missing Resources/source_dir or Resources/python_home\n");
        return 1;
    }
    snprintf(script, sizeof script, "%s/app.py", dir);
    if (chdir(dir) != 0) { perror("gestyq: chdir"); return 1; }
    setenv("GESTYQ_APP", app, 1);
    setenv("PYTHONUNBUFFERED", "1", 1);
    setenv("PYTHONHOME", pyhome, 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);

    /* python <script> <forwarded args...>; macOS adds -psn_* when launched from old Finder: drop it */
    char **av = calloc((size_t)argc + 2, sizeof *av);
    int ac = 0;
    av[ac++] = argv[0];
    av[ac++] = script;
    for (int i = 1; i < argc; i++)
        if (strncmp(argv[i], "-psn_", 5) != 0) av[ac++] = argv[i];
    av[ac] = NULL;
    return Py_BytesMain(ac, av);
}
