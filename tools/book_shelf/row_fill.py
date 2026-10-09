import math
import bpy
from mathutils import Vector, Matrix

from .geometry import (world_bbox, thickness, depth, height, bbox_center,
                       move, get_pivot, set_pivot, center_pivot, fixpivot,
                       rotate_about_pivot, set_rot, push_x,
                       y_rot_deg, radians)

EPS = 1e-9


class Stack:
    __slots__ = ("books", "spread")

    def __init__(self, books, spread):
        self.books = books
        self.spread = spread


def flatten(items):
    out = []
    for el in items:
        if isinstance(el, Stack):
            out.extend(el.books)
        else:
            out.append(el)
    return out


def rightmost_x(el):
    if isinstance(el, Stack):
        return max(world_bbox(b)[1].x for b in el.books)
    return world_bbox(el)[1].x


def leftmost_x(el):
    if isinstance(el, Stack):
        return min(world_bbox(b)[0].x for b in el.books)
    return world_bbox(el)[0].x


def make_book(src, mode, coll, pos=(0.0, 0.0, 0.0)):
    new = src.copy()
    if mode == 'COPY':
        new.data = src.data.copy()
    if new.animation_data is not None:
        new.animation_data_clear()
    if new.parent is not None:
        mw = src.matrix_world.copy()
        new.parent = None
        new.matrix_world = mw
    coll.objects.link(new)
    target = Vector(pos)
    mn, _mx = world_bbox(new)
    new.matrix_world = Matrix.Translation(target - mn) @ new.matrix_world
    set_pivot(new, target)
    new["mf_gen"] = 1
    return new


def delete_book(obj):
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass


def flip_vert(obj, prob, rnd):
    if prob <= 0.0:
        return
    if rnd.random() * 100.0 >= prob:
        return
    rotate_about_pivot(obj, Vector((0.0, 1.0, 0.0)), math.pi)
    mn, mx = world_bbox(obj)
    set_pivot(obj, mn)
    p = get_pivot(obj)
    move(obj, Vector((mx.x - p.x, 0.0, mx.z - p.z)))


def flip_horiz(obj, prob, rnd):
    if prob <= 0.0:
        return
    if rnd.random() * 100.0 >= prob:
        return
    rotate_about_pivot(obj, Vector((0.0, 0.0, 1.0)), math.pi)
    mn, mx = world_bbox(obj)
    set_pivot(obj, mn)
    p = get_pivot(obj)
    move(obj, Vector((mx.x - p.x, mx.y - p.y, 0.0)))


def push_book_to_stack(book, pile, tol):
    if not pile.spread:
        best = 0.0
        for b in pile.books:
            best = max(best, push_x(b, book, tol))
        return best
    maxx = 0.0
    for b in pile.books:
        maxx = max(maxx, world_bbox(b)[1].x)
    return maxx - world_bbox(book)[0].x


def push_stack_to_book(pile, book, tol):
    if not pile.spread:
        best = 0.0
        for b in pile.books:
            best = max(best, push_x(b, book, tol))
        return best
    minx = 0.0
    for b in pile.books:
        minx = min(minx, world_bbox(b)[0].x)
    return world_bbox(book)[1].x - minx


def push_stack_to_stack(stack_left, stack_right):
    minl = min(world_bbox(b)[0].x for b in stack_left.books)
    maxp = max(world_bbox(b)[1].x for b in stack_right.books)
    return maxp - minl


def align_push(new_item, items, tol):
    push_max = 0.0
    n = len(items)
    for i in range(3):
        idx = n - 1 - i
        if idx < 0:
            break
        prev = items[idx]
        if isinstance(new_item, Stack) and isinstance(prev, Stack):
            t = push_stack_to_stack(new_item, prev)
        elif isinstance(new_item, Stack):
            t = push_stack_to_book(new_item, prev, tol)
        elif isinstance(prev, Stack):
            t = push_book_to_stack(new_item, prev, tol)
        else:
            t = push_x(new_item, prev, tol)
        if t > push_max:
            push_max = t
        if isinstance(prev, Stack):
            break
    return push_max


def scale_row(objs, total_len, end_x):
    if end_x is None or end_x <= EPS:
        return
    f = total_len / end_x
    if abs(f - 1.0) < 1e-9:
        return
    for o in objs:
        o.matrix_world = Matrix.Diagonal((f, 1.0, 1.0, 1.0)) @ o.matrix_world
        p = get_pivot(o)
        set_pivot(o, (p.x * f, p.y, p.z))


def stack_width(s, srcs, scattered):
    if not srcs:
        return 0.0
    h = height(srcs[-1])
    w = depth(srcs[-1])
    if not scattered:
        return h
    half = abs(s.stacks_rotation * 0.5)
    rotated_w = h * math.cos(radians(half)) + w * math.cos(radians(90.0 - half))
    plain_w = h + (s.stacks_offset / 100.0) * h
    return plain_w + (rotated_w - h)


def make_stack(s, srcs, rnd, make, scattered):
    if not srcs:
        return None
    count = rnd.randint(min(s.stacks_min_books, s.stacks_max_books),
                        max(s.stacks_min_books, s.stacks_max_books))
    centr = (s.stacks_align == 'CENTER')
    front_init = (s.stacks_initial == 'FRONT')
    pile = []
    last_pick = -1
    for _i in range(count):
        roll = rnd.randrange(len(srcs))
        while pile and len(srcs) > 1 and roll == last_pick:
            roll = rnd.randrange(len(srcs))
        last_pick = roll
        nb = make(srcs[roll])
        th = thickness(nb)
        flip_vert(nb, s.vert_flip, rnd)
        flip_horiz(nb, s.hor_flip, rnd)
        center_pivot(nb)
        if centr:
            p = get_pivot(nb)
            move(nb, Vector((-p.x, -p.y, -p.z)))
        else:
            move(nb, Vector((-th * 0.5, 0.0, 0.0)))
        ang = math.radians(90.0 if front_init else -90.0)
        rotate_about_pivot(nb, Vector((0.0, 1.0, 0.0)), ang)
        p = get_pivot(nb)
        move(nb, Vector((0.0, 0.0, -p.z + height(nb) * 0.5)))
        if pile:
            move(nb, Vector((0.0, 0.0, world_bbox(pile[-1])[1].z)))
        pile.append(nb)

    if centr:
        best_y = max(world_bbox(b)[1].y for b in pile)
        for b in pile:
            move(b, Vector((0.0, best_y, 0.0)))

    if scattered:
        max_h = max(height(n) for n in srcs)
        max_w = max(depth(n) for n in srcs)
        off_x = (s.stacks_offset / 100.0) * max_h * 0.5
        off_y = (s.stacks_offset / 100.0) * max_w * 0.5
        half_rot = s.stacks_rotation * 0.5
        for o in pile:
            move(o, Vector((rnd.uniform(-off_x, off_x),
                            rnd.uniform(-off_y, off_y), 0.0)))
            rotate_about_pivot(o, Vector((0.0, 0.0, 1.0)),
                               radians(rnd.uniform(-half_rot, half_rot)))

    tallest = height(srcs[-1])
    for o in pile:
        move(o, Vector((-tallest, 0.0, 0.0)))
    return Stack(pile, scattered)


def fill_standing(s, items, row_len, srcs_by_t, rnd, tol, make):
    maxx = rightmost_x(items[-1]) if items else 0.0
    n = len(srcs_by_t)
    for i in range(n):
        src = srcs_by_t[n - 1 - i]
        if thickness(src) <= (row_len - maxx):
            nb = make(src, (-thickness(src), 0.0, 0.0))
            flip_vert(nb, s.vert_flip, rnd)
            flip_horiz(nb, s.hor_flip, rnd)
            push = align_push(nb, items, tol)
            move(nb, Vector((push, 0.0, 0.0)))
            maxx = world_bbox(nb)[1].x
            items.append(nb)
    scale_row(flatten(items), row_len, maxx)
    return True


def fill_leaning(s, items, row_len, srcs_by_t, rnd, tol, make, lean_right):
    angle = 90.0 if lean_right else -90.0
    last = items[-1] if items else None
    if last is not None and not isinstance(last, Stack):
        ry = y_rot_deg(last)
        if lean_right and ry > 0.0001:
            angle = ry
        if (not lean_right) and ry < -0.0001:
            angle = ry

    roll = rnd.randrange(len(srcs_by_t))
    nb = make(srcs_by_t[roll], (-thickness(srcs_by_t[roll]), 0.0, 0.0))
    best_diff = height(nb)
    flip_vert(nb, s.vert_flip, rnd)
    flip_horiz(nb, s.hor_flip, rnd)
    push = align_push(nb, items, tol)
    move(nb, Vector((push, 0.0, 0.0)))

    if world_bbox(nb)[1].x <= row_len:
        best_angle = 0.0
        guard = 0
        while ((lean_right and angle >= -0.0001)
               or ((not lean_right) and angle >= -90.0001)):
            guard += 1
            if guard > 400:
                break
            set_rot(nb, 0.0, radians(angle), 0.0)
            mn, mx = world_bbox(nb)
            move(nb, Vector((-mx.x, 0.0, -mn.z)))
            push = align_push(nb, items, tol)
            move(nb, Vector((push, 0.0, 0.0)))
            mx2 = world_bbox(nb)[1].x
            if abs(mx2 - row_len) < best_diff:
                best_diff = abs(mx2 - row_len)
                best_angle = angle
            angle -= 1.0

        if (best_angle >= s.leaning_min_angle) and (best_angle <= s.leaning_max_angle):
            set_rot(nb, 0.0, radians(best_angle), 0.0)
            mn, mx = world_bbox(nb)
            move(nb, Vector((-mx.x, 0.0, -mn.z)))
            push = align_push(nb, items, tol)
            move(nb, Vector((push, 0.0, 0.0)))
            items.append(nb)
            return True
        delete_book(nb)
        return False

    delete_book(nb)
    return False


def make_row(s, srcs_by_h, srcs_by_t, row_len, rnd, tol, make, progress=None):
    if (not srcs_by_h) or row_len <= EPS:
        return []

    items = []
    dummy = make(srcs_by_h[-1])
    move(dummy, Vector((-thickness(dummy), 0.0, 0.0)))
    items.append(dummy)

    right_edge = 0.0
    last_pick = -1
    book_index = len(srcs_by_h) - 1

    stacks_scatter_w = s.stacks_divergence
    standing_w = s.standing_prob if s.use_standing else 0.0
    leaning_w = s.leaning_prob if s.use_leaning else 0.0
    stacks_w = 0.0
    if s.use_stacks:
        stacks_w = max(0.0, 100.0 - standing_w - leaning_w)

    done = False
    guard = 0
    while (not done) and (row_len - right_edge) > 0.0:
        guard += 1
        if guard > 5000:
            break
        if progress is not None:
            try:
                progress(min(1.0, max(0.0, right_edge / row_len)))
            except Exception:
                pass

        roll = rnd.uniform(0.0, 100.0)
        if roll < standing_w:
            typ = 1
        elif roll < (standing_w + leaning_w):
            typ = 2
        elif stacks_w > 0.0:
            typ = 3
        else:
            typ = 0

        if typ == 0:
            break

        if typ == 1:
            lo = min(s.standing_min_books, s.standing_max_books)
            hi = max(s.standing_min_books, s.standing_max_books)
            for _i in range(rnd.randint(lo, hi)):
                if len(srcs_by_h) > 1:
                    while book_index == last_pick:
                        book_index = rnd.randrange(len(srcs_by_h))
                else:
                    book_index = 0
                src = srcs_by_h[book_index]
                if (right_edge + thickness(src)) <= row_len:
                    pos_x = -(thickness(items[0])) - thickness(src) - 1.0
                    nb = make(src, (pos_x, 0.0, 0.0))
                    flip_vert(nb, s.vert_flip, rnd)
                    flip_horiz(nb, s.hor_flip, rnd)
                    push = align_push(nb, items, tol)
                    move(nb, Vector((push, 0.0, 0.0)))
                    if world_bbox(nb)[1].x <= row_len:
                        items.append(nb)
                        right_edge = world_bbox(nb)[1].x
                        last_pick = book_index
                    else:
                        delete_book(nb)
                        fill_standing(s, items, row_len, srcs_by_t, rnd, tol, make)
                        standing_w = leaning_w = stacks_w = 0.0
                        done = True
                        break
                else:
                    fill_standing(s, items, row_len, srcs_by_t, rnd, tol, make)
                    standing_w = leaning_w = stacks_w = 0.0
                    done = True
                    break

        elif typ == 3:
            centr = (s.stacks_align == 'CENTER')
            front_init = (s.stacks_initial == 'FRONT')
            scattered = rnd.uniform(0.0, 100.0) <= stacks_scatter_w
            stack_w = stack_width(s, srcs_by_h, scattered)
            last = items[-1]
            cant_fit = False
            if (not isinstance(last, Stack)) and (y_rot_deg(last) > 0.0001):
                if abs(stacks_scatter_w - 100.0) > EPS:
                    scattered = False
                else:
                    cant_fit = True
            protruding = rightmost_x(last)
            if (row_len - protruding) >= stack_w:
                if not cant_fit:
                    new_stack = make_stack(s, srcs_by_h, rnd, make, scattered)
                    if new_stack is not None:
                        push = align_push(new_stack, items, tol)
                        for b in new_stack.books:
                            move(b, Vector((push, 0.0, 0.0)))
                        items.append(new_stack)
                        right_edge = max(world_bbox(b)[1].x for b in new_stack.books)
            else:
                if scattered and abs(stacks_scatter_w - 100.0) > EPS:
                    stacks_scatter_w = 0.0
                else:
                    if leaning_w > 0.0 and standing_w > 0.0:
                        leaning_w += stacks_w * 0.5
                        standing_w += stacks_w * 0.5
                    elif leaning_w > 0.0:
                        leaning_w += stacks_w
                    elif standing_w > 0.0:
                        standing_w += stacks_w
                    stacks_w = 0.0

        elif typ == 2:
            lo_a = min(s.leaning_min_angle, s.leaning_max_angle)
            hi_a = max(s.leaning_min_angle, s.leaning_max_angle)
            minrot = rnd.uniform(lo_a, hi_a)
            if rnd.uniform(0.0, 100.0) < s.leaning_divergence:
                minrot = rnd.uniform(lo_a, (lo_a + hi_a) * 0.5)
                maxrot = rnd.uniform((lo_a + hi_a) * 0.5, hi_a)
            else:
                maxrot = minrot

            lo = min(s.leaning_min_books, s.leaning_max_books)
            hi = max(s.leaning_min_books, s.leaning_max_books)
            count = rnd.randint(lo, hi)
            angles = [minrot, maxrot]
            if count > 2:
                for _j in range(count - 2):
                    angles.append(rnd.uniform(minrot, maxrot))
            angles.sort()

            last = items[-1]
            to_left = False
            if s.lean_dir == 'LEFT' and not (isinstance(last, Stack) and last.spread):
                to_left = True
            elif s.lean_dir == 'BOTH':
                if (rnd.uniform(0.0, 1.0) > 0.5) and not (isinstance(last, Stack) and last.spread):
                    to_left = True

            if to_left:
                angles = [-t for t in angles]
            else:
                angles.reverse()

            if not ((not to_left) and s.lean_dir == 'LEFT'):
                for it in range(count):
                    if len(srcs_by_h) > 1:
                        while book_index == last_pick:
                            book_index = rnd.randrange(len(srcs_by_h))
                    else:
                        book_index = 0
                    src = srcs_by_h[book_index]
                    pos_x = -(thickness(items[0])) - thickness(src) - 1.0
                    nb = make(src, (pos_x, 0.0, 0.0))
                    flip_vert(nb, s.vert_flip, rnd)
                    flip_horiz(nb, s.hor_flip, rnd)

                    can_lean = True
                    if not isinstance(last, Stack):
                        ry = y_rot_deg(last)
                        if to_left:
                            if ry < -0.0001 and ry < angles[it]:
                                can_lean = False
                        else:
                            if ry > 0.0001 and ry < angles[it]:
                                can_lean = False
                    if can_lean:
                        set_rot(nb, 0.0, radians(angles[it]), 0.0)
                    else:
                        set_rot(nb, 0.0, radians(y_rot_deg(last)), 0.0)

                    mn, mx = world_bbox(nb)
                    move(nb, Vector((-(mx.x - mn.x), 0.0, -mn.z)))
                    push = align_push(nb, items, tol)
                    move(nb, Vector((push, 0.0, 0.0)))

                    if world_bbox(nb)[1].x <= row_len:
                        items.append(nb)
                        right_edge = world_bbox(nb)[1].x
                        last_pick = book_index
                        last = nb
                    else:
                        leans_right = y_rot_deg(nb) > 0.0001
                        delete_book(nb)
                        filled = fill_leaning(s, items, row_len, srcs_by_t, rnd, tol,
                                              make, leans_right)
                        if (not filled) and standing_w > 0.0:
                            fill_standing(s, items, row_len, srcs_by_t, rnd, tol, make)
                        else:
                            maxx = rightmost_x(items[-1]) if items else 0.0
                            scale_row(flatten(items), row_len, maxx)
                        standing_w = leaning_w = stacks_w = 0.0
                        done = True
                        break
            else:
                if standing_w == 0.0 and stacks_w == 0.0:
                    leaning_w = 0.0

    if items:
        delete_book(items[0])
        items.pop(0)

    if items and s.standing_prob == 0.0 and s.leaning_prob == 0.0:
        right_end = rightmost_x(items[-1])
        rest = row_len - right_end
        if rest > 0.0:
            r = rnd.uniform(0.0, 10.0)
            if r < 2.0:
                d = rest
            elif r < 8.0:
                d = rnd.uniform(0.0, rest)
            else:
                d = 0.0
            if abs(d) > EPS:
                for o in flatten(items):
                    move(o, Vector((d, 0.0, 0.0)))

    return items
