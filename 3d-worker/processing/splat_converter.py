"""
Convert a 3D Gaussian Splatting .ply file to .splat format for web viewing.

The .splat format is a compact binary format used by browser-based viewers
like @mkkellogg/gaussian-splats-3d. Each Gaussian is stored as 32 bytes:
  - Position:  3 × float32 = 12 bytes
  - Scale:     3 × float32 = 12 bytes
  - Color:     4 × uint8   =  4 bytes (RGBA)
  - Rotation:  4 × uint8   =  4 bytes (normalized quaternion)
"""

import numpy as np
import struct
import os


SH_C0 = 0.28209479177387814  # Zeroth-order spherical harmonic constant


def ply_to_splat(input_ply_path, output_splat_path):
    """
    Convert a 3DGS .ply file to .splat format for web viewers.
    
    Args:
        input_ply_path: Path to input .ply file from 3DGS training
        output_splat_path: Path for output .splat file
        
    Returns:
        str: Path to the output .splat file
    """
    from plyfile import PlyData
    
    plydata = PlyData.read(input_ply_path)
    vertex = plydata['vertex']
    n = len(vertex['x'])
    
    print(f"  Converting {n} Gaussians from PLY to SPLAT...")
    
    # ── Extract raw data ──
    x = vertex['x'].astype(np.float32)
    y = vertex['y'].astype(np.float32)
    z = vertex['z'].astype(np.float32)
    
    # Scales (stored as log-scale in PLY)
    scale_0 = vertex['scale_0'].astype(np.float32)
    scale_1 = vertex['scale_1'].astype(np.float32)
    scale_2 = vertex['scale_2'].astype(np.float32)
    
    # Rotations (quaternion wxyz)
    rot_0 = vertex['rot_0'].astype(np.float32)
    rot_1 = vertex['rot_1'].astype(np.float32)
    rot_2 = vertex['rot_2'].astype(np.float32)
    rot_3 = vertex['rot_3'].astype(np.float32)
    
    # Colors (DC spherical harmonics coefficients)
    r_sh = vertex['f_dc_0'].astype(np.float32)
    g_sh = vertex['f_dc_1'].astype(np.float32)
    b_sh = vertex['f_dc_2'].astype(np.float32)
    
    # Opacity (logit space)
    opacity = vertex['opacity'].astype(np.float32)
    
    # ── Convert SH DC → RGB (0-255) ──
    colors_r = np.clip((0.5 + SH_C0 * r_sh) * 255, 0, 255).astype(np.uint8)
    colors_g = np.clip((0.5 + SH_C0 * g_sh) * 255, 0, 255).astype(np.uint8)
    colors_b = np.clip((0.5 + SH_C0 * b_sh) * 255, 0, 255).astype(np.uint8)
    
    # ── Convert opacity (sigmoid) ──
    alpha = np.clip((1.0 / (1.0 + np.exp(-opacity))) * 255, 0, 255).astype(np.uint8)
    
    # ── Normalize quaternions → uint8 ──
    quat_norm = np.sqrt(rot_0**2 + rot_1**2 + rot_2**2 + rot_3**2)
    quat_norm = np.maximum(quat_norm, 1e-10)  # Prevent division by zero
    rot_0 /= quat_norm
    rot_1 /= quat_norm
    rot_2 /= quat_norm
    rot_3 /= quat_norm
    
    rot_0_u8 = np.clip(rot_0 * 128 + 128, 0, 255).astype(np.uint8)
    rot_1_u8 = np.clip(rot_1 * 128 + 128, 0, 255).astype(np.uint8)
    rot_2_u8 = np.clip(rot_2 * 128 + 128, 0, 255).astype(np.uint8)
    rot_3_u8 = np.clip(rot_3 * 128 + 128, 0, 255).astype(np.uint8)
    
    # ── Exponentiate scales (PLY stores log-scale) ──
    exp_scale_0 = np.exp(scale_0)
    exp_scale_1 = np.exp(scale_1)
    exp_scale_2 = np.exp(scale_2)
    
    # ── Sort by opacity (most opaque first → better rendering) ──
    sort_idx = np.argsort(-alpha)
    
    # ── Write binary .splat file (32 bytes per Gaussian) ──
    with open(output_splat_path, 'wb') as f:
        for i in sort_idx:
            # Position (3 × float32 = 12 bytes)
            f.write(struct.pack('<fff', x[i], y[i], z[i]))
            # Scale (3 × float32 = 12 bytes)
            f.write(struct.pack('<fff', exp_scale_0[i], exp_scale_1[i], exp_scale_2[i]))
            # Color + Alpha (4 × uint8 = 4 bytes)
            f.write(struct.pack('BBBB', colors_r[i], colors_g[i], colors_b[i], alpha[i]))
            # Rotation (4 × uint8 = 4 bytes)
            f.write(struct.pack('BBBB', rot_0_u8[i], rot_1_u8[i], rot_2_u8[i], rot_3_u8[i]))
    
    file_size_mb = os.path.getsize(output_splat_path) / 1024 / 1024
    print(f"  Converted {n} Gaussians → {output_splat_path} ({file_size_mb:.1f} MB)")
    
    return output_splat_path
