import math
from typing import Optional


def earcut(data, holeIndices=None, dim=2):
    hasHoles = bool(holeIndices)
    outerLen = holeIndices[0] * dim if hasHoles else len(data)
    outerNode = linkedList(data, 0, outerLen, dim, True)
    triangles = []

    if (not outerNode) or outerNode.next == outerNode.prev:
        return triangles

    minX = minY = invSize = None

    if hasHoles:
        outerNode = eliminateHoles(data, holeIndices, outerNode, dim)

    # if the shape is not too simple, we'll use z-order curve hash later; calculate polygon bbox
    if len(data) > 80 * dim:
        minX = maxX = data[0]
        minY = maxY = data[1]

        for i in range(dim, outerLen, dim):
            x = data[i]
            y = data[i + 1]
            if x < minX:
                minX = x
            if y < minY:
                minY = y
            if x > maxX:
                maxX = x
            if y > maxY:
                maxY = y

        # minX, minY and invSize are later used to transform coords into integers for z-order calculation
        invSize = max(maxX - minX, maxY - minY)
        invSize = 32767 / invSize if invSize != 0 else 0

    earcutLinked(outerNode, triangles, dim, minX, minY, invSize)

    return triangles


# create a circular doubly linked list from polygon points in the specified winding order
def linkedList(data, start, end, dim, clockwise):
    last = None

    if clockwise == (signedArea(data, start, end, dim) > 0):
        for i in range(start, end, dim):
            last = insertNode(i, data[i], data[i + 1], last)
    else:
        for i in reversed(range(start, end, dim)):
            last = insertNode(i, data[i], data[i + 1], last)

    if last and equals(last, last.next):
        removeNode(last)
        last = last.next

    return last


# eliminate colinear or duplicate points
def filterPoints(start, end=None):
    if not start:
        return start

    if not end:
        end = start

    p = start
    while True:
        again = False

        if not p.steiner and (equals(p, p.next) or area(p.prev, p, p.next) == 0):
            removeNode(p)
            p = end = p.prev
            if p == p.next:
                break
            again = True

        else:
            p = p.next

        if (not again) and p == end:
            break

    return end


# main ear slicing loop which triangulates a polygon (given as a linked list)
def earcutLinked(ear, triangles, dim, minX, minY, invSize, _pass=0):
    if not ear:
        return

    # interlink polygon nodes in z-order
    if not _pass and invSize:
        indexCurve(ear, minX, minY, invSize)

    stop = ear

    # iterate through ears, slicing them one by one
    while ear.prev != ear.next:
        prev = ear.prev
        next = ear.next

        if isEarHashed(ear, minX, minY, invSize) if invSize else isEar(ear):
            # cut off the triangle
            triangles.append(prev.i // dim)
            triangles.append(ear.i // dim)
            triangles.append(next.i // dim)

            removeNode(ear)

            # skipping the next vertex leads to less sliver triangles
            ear = next.next
            stop = next.next

            continue

        ear = next

        # if we looped through the whole remaining polygon and can't find any more ears
        if ear == stop:
            # try filtering points and slicing again
            if not _pass:
                earcutLinked(filterPoints(ear), triangles, dim, minX, minY, invSize, 1)

            # if this didn't work, try curing all small self-intersections locally
            elif _pass == 1:
                ear = cureLocalIntersections(filterPoints(ear), triangles, dim)
                earcutLinked(ear, triangles, dim, minX, minY, invSize, 2)

            # as a last resort, try splitting the remaining polygon into two
            elif _pass == 2:
                splitEarcut(ear, triangles, dim, minX, minY, invSize)

            break


# check whether a polygon node forms a valid ear with adjacent nodes
def isEar(ear):
    a = ear.prev
    b = ear
    c = ear.next

    if area(a, b, c) >= 0:
        return False  # reflex, can't be an ear

    # now make sure we don't have other points inside the potential ear
    ax = a.x
    ay = a.y
    bx = b.x
    by = b.y
    cx = c.x
    cy = c.y

    # triangle bbox; min & max are calculated like this for speed
    x0 = (ax if ax < cx else cx) if ax < bx else (bx if bx < cx else cx)
    y0 = (ay if ay < cy else cy) if ay < by else (by if by < cy else cy)
    x1 = (ax if ax > cx else cx) if ax > bx else (bx if bx > cx else cx)
    y1 = (ay if ay > cy else cy) if ay > by else (by if by > cy else cy)

    p = c.next
    while p != a:
        if (
            p.x >= x0
            and p.x <= x1
            and p.y >= y0
            and p.y <= y1
            and pointInTriangle(ax, ay, bx, by, cx, cy, p.x, p.y)
            and area(p.prev, p, p.next) >= 0
        ):
            return False
        p = p.next

    return True


def isEarHashed(ear, minX, minY, invSize):
    a = ear.prev
    b = ear
    c = ear.next

    if area(a, b, c) >= 0:
        return False  # reflex, can't be an ear

    ax = a.x
    ay = a.y
    bx = b.x
    by = b.y
    cx = c.x
    cy = c.y

    # triangle bbox; min & max are calculated like this for speed
    x0 = (ax if ax < cx else cx) if ax < bx else (bx if bx < cx else cx)
    y0 = (ay if ay < cy else cy) if ay < by else (by if by < cy else cy)
    x1 = (ax if ax > cx else cx) if ax > bx else (bx if bx > cx else cx)
    y1 = (ay if ay > cy else cy) if ay > by else (by if by > cy else cy)

    # z-order range for the current triangle bbox
    minZ = zOrder(x0, y0, minX, minY, invSize)
    maxZ = zOrder(x1, y1, minX, minY, invSize)

    p = ear.prevZ
    n = ear.nextZ

    # look for points inside the triangle in both directions
    while p and p.z >= minZ and n and n.z <= maxZ:
        if (
            p.x >= x0
            and p.x <= x1
            and p.y >= y0
            and p.y <= y1
            and p != a
            and p != c
            and pointInTriangle(ax, ay, bx, by, cx, cy, p.x, p.y)
            and area(p.prev, p, p.next) >= 0
        ):
            return False
        p = p.prevZ

        if (
            n.x >= x0
            and n.x <= x1
            and n.y >= y0
            and n.y <= y1
            and n != a
            and n != c
            and pointInTriangle(ax, ay, bx, by, cx, cy, n.x, n.y)
            and area(n.prev, n, n.next) >= 0
        ):
            return False
        n = n.nextZ

    # look for remaining points in decreasing z-order
    while p and p.z >= minZ:
        if (
            p != ear.prev
            and p != ear.next
            and pointInTriangle(ax, ay, bx, by, cx, cy, p.x, p.y)
            and area(p.prev, p, p.next) >= 0
        ):
            return False
        p = p.prevZ

    # look for remaining points in increasing z-order
    while n and n.z <= maxZ:
        if (
            n != ear.prev
            and n != ear.next
            and pointInTriangle(ax, ay, bx, by, cx, cy, n.x, n.y)
            and area(n.prev, n, n.next) >= 0
        ):
            return False
        n = n.nextZ

    return True


# go through all polygon nodes and cure small local self-intersections
def cureLocalIntersections(start, triangles, dim):
    p = start
    while True:
        a = p.prev
        b = p.next.next

        if (
            not equals(a, b)
            and intersects(a, p, p.next, b)
            and locallyInside(a, b)
            and locallyInside(b, a)
        ):
            triangles.append(a.i // dim)
            triangles.append(p.i // dim)
            triangles.append(b.i // dim)

            # remove two nodes involved
            removeNode(p)
            removeNode(p.next)

            p = start = b

        p = p.next
        if p == start:
            break

    return filterPoints(p)


# try splitting polygon into two and triangulate them independently
def splitEarcut(start, triangles, dim, minX, minY, invSize):
    # look for a valid diagonal that divides the polygon into two
    a = start
    while True:
        b = a.next.next
        while b != a.prev:
            if a.i != b.i and isValidDiagonal(a, b):
                # split the polygon in two by the diagonal
                c = splitPolygon(a, b)

                # filter colinear points around the cuts
                a = filterPoints(a, a.next)
                c = filterPoints(c, c.next)

                # run earcut on each half
                earcutLinked(a, triangles, dim, minX, minY, invSize)
                earcutLinked(c, triangles, dim, minX, minY, invSize)
                return
            b = b.next
        a = a.next
        if a == start:
            break


# link every hole into the outer loop, producing a single-ring polygon without holes
def eliminateHoles(data, holeIndices, outerNode, dim):
    queue = []
    _len = len(holeIndices)

    for i in range(_len):
        start = holeIndices[i] * dim
        end = holeIndices[i + 1] * dim if i < _len - 1 else len(data)
        lst = linkedList(data, start, end, dim, False)
        if lst == lst.next:
            lst.steiner = True
        queue.append(getLeftmost(lst))

    queue.sort(key=lambda i: i.x)

    # process holes from left to right
    for q_i in queue:
        outerNode = eliminateHole(q_i, outerNode)

    return outerNode


# find a bridge between vertices that connects hole with an outer ring and and link it
def eliminateHole(hole, outerNode):
    bridge = findHoleBridge(hole, outerNode)
    if not bridge:
        return outerNode

    bridgeReverse = splitPolygon(bridge, hole)

    filterPoints(bridgeReverse, bridgeReverse.next)
    return filterPoints(bridge, bridge.next)


# David Eberly's algorithm for finding a bridge between hole and outer polygon
def findHoleBridge(hole, outerNode):
    p = outerNode
    hx = hole.x
    hy = hole.y
    qx = -math.inf
    m = None

    # find a segment intersected by a ray from the hole's leftmost point to the left
    # segment's endpoint with lesser x will be potential connection point
    while True:
        px = p.x
        py = p.y
        if hy <= py and hy >= p.next.y and p.next.y != py:
            x = px + (hy - py) * (p.next.x - px) / (p.next.y - py)
            if x <= hx and x > qx:
                qx = x
                m = p if px < p.next.x else p.next
                if x == hx:
                    # hole touches outer segment; pick leftmost endpoint
                    return m
        p = p.next
        if p == outerNode:
            break

    if not m:
        return None

    if hx == qx:
        return m  # hole touches outer segment; pick leftmost endpoint

    # look for points inside the triangle of hole point, segment intersection and endpoint
    # if there are no points found, we have a valid connection
    # otherwise choose the point of the minimum angle with the ray as connection point

    stop = m
    mx = m.x
    my = m.y
    tanMin = math.inf

    p = m

    while True:
        px = p.x
        py = p.y
        if (
            hx >= px
            and px >= mx
            and hx != px
            and pointInTriangle(
                hx if hy < my else qx,
                hy,
                mx,
                my,
                qx if hy < my else hx,
                hy,
                px,
                py,
            )
        ):
            tan = abs(hy - py) / (hx - px)  # tangential

            if locallyInside(p, hole) and (
                tan < tanMin
                or (
                    tan == tanMin
                    and (px > m.x or (px == m.x and sectorContainsSector(m, p)))
                )
            ):
                m = p
                tanMin = tan

        p = p.next
        if p == stop:
            break

    return m


# whether sector in vertex m contains sector in vertex p in the same coordinates
def sectorContainsSector(m, p):
    return area(m.prev, m, p.prev) < 0 and area(p.next, m, m.next) < 0


# interlink polygon nodes in z-order
def indexCurve(start, minX, minY, invSize):
    p = start
    while True:
        if p.z is None:
            p.z = zOrder(p.x, p.y, minX, minY, invSize)
        p.prevZ = p.prev
        p.nextZ = p.next
        p = p.next
        if p == start:
            break

    p.prevZ.nextZ = None
    p.prevZ = None

    sortLinked(p)


# Simon Tatham's linked list merge sort algorithm
# http://www.chiark.greenend.org.uk/~sgtatham/algorithms/listsort.html
def sortLinked(_list):
    inSize = 1

    while True:
        p = _list
        _list = None
        tail = None
        numMerges = 0

        while p:
            numMerges += 1
            q = p
            pSize = 0
            for i in range(inSize):
                pSize += 1
                q = q.nextZ
                if not q:
                    break
            qSize = inSize

            while pSize > 0 or (qSize > 0 and q):
                if pSize != 0 and (qSize == 0 or not q or p.z <= q.z):
                    e = p
                    p = p.nextZ
                    pSize -= 1
                else:
                    e = q
                    q = q.nextZ
                    qSize -= 1

                if tail:
                    tail.nextZ = e
                else:
                    _list = e

                e.prevZ = tail
                tail = e

            p = q

        tail.nextZ = None
        inSize *= 2

        if numMerges <= 1:
            break

    return _list


# z-order of a point given coords and inverse of the longer side of data bbox
def zOrder(x, y, minX, minY, invSize):
    # coords are transformed into non-negative 15-bit integer range
    x = int((x - minX) * invSize)
    y = int((y - minY) * invSize)

    x = (x | (x << 8)) & 0x00FF00FF
    x = (x | (x << 4)) & 0x0F0F0F0F
    x = (x | (x << 2)) & 0x33333333
    x = (x | (x << 1)) & 0x55555555

    y = (y | (y << 8)) & 0x00FF00FF
    y = (y | (y << 4)) & 0x0F0F0F0F
    y = (y | (y << 2)) & 0x33333333
    y = (y | (y << 1)) & 0x55555555

    return x | (y << 1)


# find the leftmost node of a polygon ring
def getLeftmost(start):
    p = start
    leftmost = start

    while True:
        if p.x < leftmost.x or (p.x == leftmost.x and p.y < leftmost.y):
            leftmost = p

        p = p.next
        if p == start:
            break

    return leftmost


# check if a point lies within a convex triangle
def pointInTriangle(ax, ay, bx, by, cx, cy, px, py):
    pax = ax - px
    pay = ay - py
    pbx = bx - px
    pby = by - py
    pcx = cx - px
    pcy = cy - py
    return (
        pcx * pay - pax * pcy >= 0
        and pax * pby - pbx * pay >= 0
        and pbx * pcy - pcx * pby >= 0
    )


# check if a diagonal between two polygon nodes is valid (lies in polygon interior)
def isValidDiagonal(a, b):
    return (
        a.next.i != b.i
        and a.prev.i != b.i
        and not intersectsPolygon(a, b)
        and (  # dones't intersect other edges
            locallyInside(a, b)
            and locallyInside(b, a)
            and middleInside(a, b)
            and (area(a.prev, a, b.prev) or area(a, b.prev, b))  # locally visible
            or equals(a, b)  # does not create opposite-facing sectors
            and area(a.prev, a, a.next) > 0
            and area(b.prev, b, b.next) > 0
        )
    )  # special zero-length case


# signed area of a triangle
def area(p, q, r):
    return (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y)


# check if two points are equal
def equals(p1, p2):
    return p1.x == p2.x and p1.y == p2.y


# check if two segments intersect
def intersects(p1, q1, p2, q2):
    o1 = sign(area(p1, q1, p2))
    o2 = sign(area(p1, q1, q2))
    o3 = sign(area(p2, q2, p1))
    o4 = sign(area(p2, q2, q1))

    if o1 != o2 and o3 != o4:
        return True  # general case

    if o1 == 0 and onSegment(p1, p2, q1):
        return True  # p1, q1 and p2 are collinear and p2 lies on p1q1
    if o2 == 0 and onSegment(p1, q2, q1):
        return True  # p1, q1 and q2 are collinear and q2 lies on p1q1
    if o3 == 0 and onSegment(p2, p1, q2):
        return True  # p2, q2 and p1 are collinear and p1 lies on p2q2
    if o4 == 0 and onSegment(p2, q1, q2):
        return True  # p2, q2 and q1 are collinear and q1 lies on p2q2

    return False


# for collinear points p, q, r, check if point q lies on segment pr
def onSegment(p, q, r):
    return (
        q.x <= max(p.x, r.x)
        and q.x >= min(p.x, r.x)
        and q.y <= max(p.y, r.y)
        and q.y >= min(p.y, r.y)
    )


def sign(num):
    if num > 0:
        return 1
    if num < 0:
        return -1
    return 0


# check if a polygon diagonal intersects any polygon segments
def intersectsPolygon(a, b):
    p = a
    while True:
        pi = p.i
        ai = a.i
        bi = b.i
        pnext = p.next
        pnexti = pnext.i
        if (
            pi != ai
            and pnexti != ai
            and pi != bi
            and pnexti != bi
            and intersects(p, pnext, a, b)
        ):
            return True

        p = pnext
        if p == a:
            break

    return False


# check if a polygon diagonal is locally inside the polygon
def locallyInside(a, b):
    aprev = a.prev
    anext = a.next
    if area(aprev, a, anext) < 0:
        return area(a, b, anext) >= 0 and area(a, aprev, b) >= 0
    else:
        return area(a, b, aprev) < 0 or area(a, anext, b) < 0


# check if the middle point of a polygon diagonal is inside the polygon
def middleInside(a, b):
    p = a
    inside = False
    px = (a.x + b.x) / 2
    py = (a.y + b.y) / 2
    while True:
        p_x = p.x
        p_y = p.y
        p_next = p.next
        p_next_y = p_next.y
        if (
            (p_y > py) != (p_next_y > py)
            and p_next.y != p_y
            and (px < (p_next.x - p_x) * (py - p_y) / (p_next_y - p_y) + p_x)
        ):
            inside = not inside
        p = p_next
        if p == a:
            break

    return inside


# link two polygon vertices with a bridge; if the vertices belong to the same ring, it splits polygon into two
# if one belongs to the outer ring and another to a hole, it merges it into a single ring
def splitPolygon(a, b):
    a2 = Node(a.i, a.x, a.y)
    b2 = Node(b.i, b.x, b.y)
    an = a.next
    bp = b.prev

    a.next = b
    b.prev = a

    a2.next = an
    an.prev = a2

    b2.next = a2
    a2.prev = b2

    bp.next = b2
    b2.prev = bp

    return b2


# create a node and optionally link it with previous one (in a circular doubly linked list)
def insertNode(i, x, y, last):
    p = Node(i, x, y)

    if not last:
        p.prev = p
        p.next = p

    else:
        p.next = last.next
        p.prev = last
        last.next.prev = p
        last.next = p

    return p


def removeNode(p):
    p.next.prev = p.prev
    p.prev.next = p.next

    if p.prevZ:
        p.prevZ.nextZ = p.nextZ

    if p.nextZ:
        p.nextZ.prevZ = p.prevZ


class Node:
    __slots__ = ["i", "x", "y", "prev", "next", "z", "prevZ", "nextZ", "steiner"]
    i: int
    x: float
    y: float
    prev: Optional["Node"]
    next: Optional["Node"]
    z: Optional[int]
    prevZ: Optional["Node"]
    nextZ: Optional["Node"]
    steiner: bool

    def __init__(self, i, x, y):
        # vertex index in coordinates array
        self.i = i

        # vertex coordinates
        self.x = x
        self.y = y

        # previous and next vertex nodes in a polygon ring
        self.prev = None
        self.next = None

        # z-order curve value
        self.z = None

        # previous and next nodes in z-order
        self.prevZ = None
        self.nextZ = None

        # indicates whether this is a steiner point
        self.steiner = False


# return a percentage difference between the polygon area and its triangulation area
# used to verify correctness of triangulation
def deviation(data, holeIndices, dim, triangles):
    hasHoles = holeIndices and len(holeIndices)
    outerLen = holeIndices[0] * dim if hasHoles else len(data)

    polygonArea = abs(signedArea(data, 0, outerLen, dim))
    if hasHoles:
        _len = len(holeIndices)
        for i in range(_len):
            start = holeIndices[i] * dim
            end = holeIndices[i + 1] * dim if i < _len - 1 else len(data)
            polygonArea -= abs(signedArea(data, start, end, dim))

    trianglesArea = 0
    for i in range(0, len(triangles), 3):
        a = triangles[i] * dim
        b = triangles[i + 1] * dim
        c = triangles[i + 2] * dim
        trianglesArea += abs(
            (data[a] - data[c]) * (data[b + 1] - data[a + 1])
            - (data[a] - data[b]) * (data[c + 1] - data[a + 1])
        )

    if polygonArea == 0 and trianglesArea == 0:
        return 0
    return abs((trianglesArea - polygonArea) / polygonArea)


def signedArea(data, start, end, dim):
    sum = 0
    j = end - dim
    for i in range(start, end, dim):
        sum += (data[j] - data[i]) * (data[i + 1] + data[j + 1])
        j = i

    return sum


# turn a polygon in a multi-dimensional array form (e.g. as in GeoJSON) into a form Earcut accepts
def flatten(data):
    dim = len(data[0][0])
    vertices = []
    holes = []
    holeIndex = 0

    for i in range(len(data)):
        for j in range(len(data[i])):
            for d in range(dim):
                vertices.append(data[i][j][d])

        if i > 0:
            holeIndex += len(data[i - 1])
            holes.append(holeIndex)

    return {"vertices": vertices, "holes": holes, "dimensions": dim}
