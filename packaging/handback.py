"""Hand root-owned files in the user's data home back to the user, via file descriptors only.

Run as root by install.sh with `python3 -I`. Refuses symlinked path components; any
root-owned entry it cannot safely chown (hard link, symlink, socket, ...) fails the install.
"""
import os
import pwd
import stat
import sys

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def main(home, user, owner_uid=0):
    pw = pwd.getpwnam(user)
    uid, gid = pw.pw_uid, pw.pw_gid
    left = []
    fds = []
    try:
        fd = os.open(home, _DIR)
        fds.append(fd)
        for part in ("Library", "Application Support", "GOV-AIOS"):
            try:
                fd = os.open(part, _DIR, dir_fd=fd)
            except FileNotFoundError:
                if part == "GOV-AIOS":
                    return 0
                raise
            fds.append(fd)
    except OSError as e:
        print(f"refusing: bad path component under {home}: {e}", file=sys.stderr)
        return 1
    try:
        data_fd = fds[-1]
        if os.fstat(data_fd).st_uid == owner_uid:
            os.fchown(data_fd, uid, gid)
        for dirpath, dirnames, filenames, dirfd in os.fwalk(".", dir_fd=data_fd, follow_symlinks=False):
            for name in dirnames + filenames:
                rel = os.path.join(dirpath, name)
                try:
                    lst = os.lstat(name, dir_fd=dirfd)
                except OSError:
                    continue
                if lst.st_uid != owner_uid:
                    continue
                if stat.S_ISLNK(lst.st_mode):
                    left.append(rel)
                    continue
                try:
                    f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dirfd)
                except OSError:
                    left.append(rel)
                    continue
                try:
                    st = os.fstat(f)
                    if st.st_uid != owner_uid:
                        continue
                    if stat.S_ISDIR(st.st_mode) or (stat.S_ISREG(st.st_mode) and st.st_nlink == 1):
                        os.fchown(f, uid, gid)
                    else:
                        left.append(rel)
                finally:
                    os.close(f)
    finally:
        for f in fds:
            os.close(f)
    if left:
        print("root-owned entries left in the data home; fix by hand:\n  " + "\n  ".join(left), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
