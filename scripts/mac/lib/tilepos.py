"""把作业里的 [x, y] 格子坐标换算成屏幕像素——照抄 MAA 的算法。

出处：MAA 的 3rdparty/include/Arknights-Tile-Pos/TileCalc2.hpp
（`camera_pos` / `camera_matrix_from_trans` / `world_to_screen` / `get_tile_world_pos`）。
关卡的格子表和相机参数在游戏机上：
`D:\\ark\\maa\\resource\\Arknights-Tile-Pos\\<stage>-...json`，
里面有 width / height / view / tiles。

**为什么要抄它而不是看图数格子**：作业里写的是 `location: [8, 3]`，
肉眼在截图上数"从上到下第三格"会数错——透视之下每列格子数不一样多，
而且按住干员时画面还会平移。这份算法是 MAA 自己用的那份，确定性的。

注意 MAA 的公式以 1280x720 为基准，实际分辨率要按比例放大。
"""
import math

DEGREE = math.pi / 180


def _mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _camera_pos(view, side, width, height):
    x, y, z = view[1 if side else 0]
    from_ratio, to_ratio = 9 / 16, 3 / 4
    t = (from_ratio - height / width) / (from_ratio - to_ratio)
    return (x - 1.4 * t, y - 2.8 * t, z)


def _camera_matrix(pos, euler, ratio, fov_2_y=20 * DEGREE, far_c=1000.0, near_c=0.3):
    cos_y, sin_y = math.cos(euler[0]), math.sin(euler[0])
    cos_x, sin_x = math.cos(euler[1]), math.sin(euler[1])
    tan_f = math.tan(fov_2_y)
    translate = [[1, 0, 0, -pos[0]], [0, 1, 0, -pos[1]], [0, 0, 1, -pos[2]], [0, 0, 0, 1]]
    m_y = [[cos_y, 0, sin_y, 0], [0, 1, 0, 0], [-sin_y, 0, cos_y, 0], [0, 0, 0, 1]]
    m_x = [[1, 0, 0, 0], [0, cos_x, -sin_x, 0], [0, -sin_x, -cos_x, 0], [0, 0, 0, 1]]
    proj = [
        [ratio / tan_f, 0, 0, 0],
        [0, 1 / tan_f, 0, 0],
        [0, 0, -(far_c + near_c) / (far_c - near_c), -(far_c * near_c * 2) / (far_c - near_c)],
        [0, 0, -1, 0],
    ]
    return _mat_mul(proj, _mat_mul(m_x, _mat_mul(m_y, translate)))


def world_to_screen(view, world, side=False, screen=(1280, 720)):
    base_w, base_h = 1280, 720
    pos = _camera_pos(view, side, base_w, base_h)
    euler = (10 * DEGREE, 30 * DEGREE, 0) if side else (0, 30 * DEGREE, 0)
    m = _camera_matrix(pos, euler, base_h / base_w)
    v = [world[0], world[1], world[2], 1.0]
    r = [sum(m[i][k] * v[k] for k in range(4)) for i in range(4)]
    r = [c / r[3] for c in r]
    r = [(c + 1) / 2 for c in r]
    return (round(r[0] * base_w * screen[0] / base_w),
            round((1 - r[1]) * base_h * screen[1] / base_h))


def tile_screen_pos(level, tile_x, tile_y, screen=(1280, 720)):  # deadcode: allow
    """level 就是那份 json（含 width/height/view/tiles）。tile_x/tile_y 用作业里的写法。"""
    w, h = level["width"], level["height"]
    tile = level["tiles"][tile_y][tile_x]
    world = (tile_x - (w - 1) / 2.0,
             (h - 1) / 2.0 - tile_y,
             tile["heightType"] * -0.4)
    return world_to_screen(level["view"], world, False, screen)
