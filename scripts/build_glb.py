# ruff: noqa
"""Generate small, original GLB teaching models (no third-party assets, no licence issues)."""
import sys
from pathlib import Path

import numpy as np
import trimesh


def col(mesh, rgba):
    mesh.visual.vertex_colors = np.tile(np.array(rgba, dtype=np.uint8), (len(mesh.vertices), 1))
    return mesh


def two_tone_sphere(radius, day=(70, 140, 230, 255), night=(15, 30, 80, 255)):
    s = trimesh.creation.icosphere(subdivisions=4, radius=radius)
    colors = np.where((s.vertices[:, 0] > 0)[:, None], np.array(day), np.array(night)).astype(np.uint8)
    s.visual.vertex_colors = colors
    return s


def earth_axis():
    earth = two_tone_sphere(1.0)
    axis = col(trimesh.creation.cylinder(radius=0.025, height=2.8), (240, 240, 240, 255))
    rot = trimesh.transformations.rotation_matrix(np.radians(23.5), [0, 0, 1])
    axis.apply_transform(rot)
    earth.apply_transform(rot)
    sun = col(trimesh.creation.icosphere(subdivisions=3, radius=0.35), (255, 200, 40, 255))
    sun.apply_translation([3.4, 0, 0])
    return trimesh.util.concatenate([earth, axis, sun])


def solar_system():
    parts = [col(trimesh.creation.icosphere(subdivisions=3, radius=1.0), (255, 190, 40, 255))]
    palette = [(160, 160, 160), (230, 190, 120), (60, 120, 220), (200, 80, 50), (220, 170, 110), (230, 210, 150), (140, 210, 220), (60, 90, 200)]
    sizes = [0.12, 0.2, 0.22, 0.16, 0.5, 0.42, 0.3, 0.3]
    x = 1.8
    for c, r in zip(palette, sizes):
        p = col(trimesh.creation.icosphere(subdivisions=3, radius=r), (*c, 255))
        p.apply_translation([x, 0, 0])
        parts.append(p)
        x += r * 2 + 0.35
    return trimesh.util.concatenate(parts)


def moon():
    m = trimesh.creation.icosphere(subdivisions=4, radius=1.0)
    colors = np.where((m.vertices[:, 0] > -0.2)[:, None], np.array((225, 225, 215, 255)), np.array((40, 40, 50, 255))).astype(np.uint8)
    m.visual.vertex_colors = colors
    return m


def atom():
    parts = [col(trimesh.creation.icosphere(subdivisions=3, radius=0.35), (220, 60, 60, 255))]
    for k in range(3):
        ring = trimesh.creation.annulus(r_min=1.0, r_max=1.03, height=0.02)
        ring.apply_transform(trimesh.transformations.rotation_matrix(np.radians(60 * k), [1, 0, 0]))
        parts.append(col(ring, (200, 200, 200, 255)))
        e = col(trimesh.creation.icosphere(subdivisions=2, radius=0.09), (60, 120, 240, 255))
        e.apply_translation([1.0, 0, 0])
        e.apply_transform(trimesh.transformations.rotation_matrix(np.radians(60 * k), [1, 0, 0]))
        parts.append(e)
    return trimesh.util.concatenate(parts)


def earth_layers():
    core = col(trimesh.creation.icosphere(subdivisions=3, radius=0.5), (255, 200, 60, 255))
    mantle = trimesh.creation.icosphere(subdivisions=3, radius=0.8)
    mantle.visual.vertex_colors = np.tile(np.array((220, 90, 40, 255), dtype=np.uint8), (len(mantle.vertices), 1))
    crust = trimesh.creation.icosphere(subdivisions=4, radius=1.0)
    # cut-away: drop the faces in one octant so the layers are visible
    keep = crust.triangles_center
    mask = ~((keep[:, 0] > 0) & (keep[:, 1] > 0) & (keep[:, 2] > 0))
    mantle_keep = mantle.triangles_center
    mmask = ~((mantle_keep[:, 0] > 0) & (mantle_keep[:, 1] > 0) & (mantle_keep[:, 2] > 0))
    crust.update_faces(mask)
    mantle.update_faces(mmask)
    col(crust, (60, 150, 80, 255))
    col(mantle, (220, 90, 40, 255))
    return trimesh.util.concatenate([crust, mantle, core])


MODELS = {
    "earth-axis": earth_axis,
    "solar-system": solar_system,
    "moon": moon,
    "atom": atom,
    "earth-layers": earth_layers,
    "cube": lambda: col(trimesh.creation.box(extents=[1.6, 1.6, 1.6]), (70, 130, 230, 255)),
    "pyramid": lambda: col(trimesh.creation.cone(radius=1.0, height=1.6, sections=3), (240, 160, 60, 255)),
}

if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in MODELS.items():
        mesh = fn()
        data = trimesh.Scene(mesh).export(file_type="glb")
        (out / f"{name}.glb").write_bytes(data)
        print(name, len(data), "bytes")
