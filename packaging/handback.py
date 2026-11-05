"""Hand root-owned files in the user's data home back to the user, via file descriptors only.

Run as root by install.sh with `python3 -I`. Refuses symlinked path components; any
root-owned entry it cannot safely chown (hard link, symlink, socket, ...) fails the install.
"""
import os
import pwd
import stat
import sys

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _same(a, b):
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def walk(dfd, rel, owner_uid, uid, gid, left):
    """Hand-written no-follow walk: nothing is opened without O_NOFOLLOW|O_NONBLOCK, nothing skipped silently."""
    names = os.listdir(dfd)  # listdir(fd) does not close dfd
    for name in names:
        path = os.path.join(rel, name)
        try:
            lst = os.lstat(name, dir_fd=dfd)
        except FileNotFoundError:
            continue
        except OSError:
            left.append(path)
            continue
        root = lst.st_uid == owner_uid
        if root and not (stat.S_ISREG(lst.st_mode) or stat.S_ISDIR(lst.st_mode)):
            left.append(path)  # symlink, FIFO, socket, device: never opened
            continue
        if stat.S_ISDIR(lst.st_mode):
            try:
                fd = os.open(name, _DIR | os.O_NONBLOCK, dir_fd=dfd)
            except OSError:
                left.append(path)
                continue
            try:
                st = os.fstat(fd)
                if not (stat.S_ISDIR(st.st_mode) and _same(st, lst)):
                    left.append(path)
                    continue
                if root:
                    os.fchown(fd, uid, gid)
                walk(fd, path, owner_uid, uid, gid, left)
            except OSError:
                left.append(path)
            finally:
                os.close(fd)
        elif root and stat.S_ISREG(lst.st_mode):
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
            except OSError:
                left.append(path)
                continue
            try:
                st = os.fstat(fd)
                if stat.S_ISREG(st.st_mode) and _same(st, lst) and st.st_nlink == 1:
                    os.fchown(fd, uid, gid)
                else:
                    left.append(path)
            finally:
                os.close(fd)


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
        walk(data_fd, ".", owner_uid, uid, gid, left)
    except OSError as e:
        print(f"refusing: cannot walk the data home: {e}", file=sys.stderr)
        return 1
    finally:
        for f in fds:
            os.close(f)
    if left:
        print("root-owned entries left in the data home; fix by hand:\n  " + "\n  ".join(left), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
