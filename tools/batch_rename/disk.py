import os

from . import naming

TMP_TAG = ".brntmp"

def _norm(p):
    return os.path.normcase(os.path.abspath(p))

def _insert_suffix(path, tag):
    folder = os.path.dirname(path)
    stem, ext = naming.split_ext(os.path.basename(path))
    return os.path.join(folder, stem + tag + ext)

def make_file_unit(entry, old_abs, wanted_abs):
    return {"kind": "file", "entry": entry, "old": old_abs, "wanted": wanted_abs,
            "frames": None, "final": None, "pattern": None, "followers": []}

def make_seq_unit(entry, frames, wanted_pattern):
    return {"kind": "seq", "entry": entry, "old": None, "wanted": wanted_pattern,
            "frames": frames, "final": None, "pattern": None, "followers": []}

def _conflict(targets, taken, protected):
    for t in targets:
        nt = _norm(t)
        if nt in taken:
            return True
        if os.path.exists(t) and nt not in protected:
            return True
    return False

def plan(units):
    protected = set()
    for u in units:
        if u["kind"] == "file":
            protected.add(_norm(u["old"]))
        else:
            for _n, p, _d in u["frames"]:
                protected.add(_norm(p))

    taken = set()
    moves = []
    errors = []

    for u in units:
        base = u["wanted"]
        tag = 0
        targets = None
        while True:
            if u["kind"] == "file":
                final = base if tag == 0 else _insert_suffix(base, "_%d" % tag)
                cand = [final]
            else:
                pat = base if tag == 0 else _insert_suffix(base, "_%d" % tag)
                final = pat
                cand = [naming.sequence_frame_name(pat, d) for _n, _p, d in u["frames"]]
            if not _conflict(cand, taken, protected):
                u["final"] = final
                targets = cand
                break
            tag += 1
            if tag > 50:
                errors.append((u, "同名文件太多，自动避让失败"))
                break
        if targets is None:
            continue
        for t in targets:
            taken.add(_norm(t))

        if u["kind"] == "file":
            if _norm(u["old"]) != _norm(u["final"]):
                moves.append((u["old"], u["final"], u))
        else:
            for _n, p, d in u["frames"]:
                np = naming.sequence_frame_name(u["final"], d)
                if _norm(p) != _norm(np):
                    moves.append((p, np, u))

    return moves, errors

def run_moves(moves):
    if not moves:
        return 0, []

    done = []

    for i, (old, _new, _u) in enumerate(moves):
        tmp = "%s%s%03d" % (old, TMP_TAG, i)
        try:
            os.replace(old, tmp)
        except OSError as exc:
            for t, o in reversed(done):
                try:
                    os.replace(t, o)
                except OSError:
                    pass
            return 0, ["无法改动 %s：%s（已回滚）" % (os.path.basename(old), exc)]
        done.append((tmp, old))

    for i, (_old, new, _u) in enumerate(moves):
        tmp = "%s%s%03d" % (moves[i][0], TMP_TAG, i)
        try:
            os.replace(tmp, new)
        except OSError as exc:
            for j in range(i, len(moves)):
                t = "%s%s%03d" % (moves[j][0], TMP_TAG, j)
                try:
                    os.replace(t, moves[j][0])
                except OSError:
                    pass
            for j in range(i):
                try:
                    os.replace(moves[j][1], moves[j][0])
                except OSError:
                    pass
            return 0, ["无法写入 %s：%s（已回滚）" % (os.path.basename(new), exc)]

    return len(moves), []
