import numpy as np
from plyfile import PlyData
import struct
import os

def ply_to_splat(input_ply_path, output_splat_path):
    """Convert a 3DGS .ply file to .splat format for web viewers."""
    plydata = PlyData.read(input_ply_path)
    vertex = plydata['vertex']
    
    # Extract positions
    x = vertex['x'].astype(np.float32)
    y = vertex['y'].astype(np.float32) 
    z = vertex['z'].astype(np.float32)
    
    # Extract scales (log scale)
    scale_0 = vertex['scale_0'].astype(np.float32)
    scale_1 = vertex['scale_1'].astype(np.float32)
    scale_2 = vertex['scale_2'].astype(np.float32)
    
    # Extract rotations (quaternion)
    rot_0 = vertex['rot_0'].astype(np.float32)
    rot_1 = vertex['rot_1'].astype(np.float32)
    rot_2 = vertex['rot_2'].astype(np.float32)
    rot_3 = vertex['rot_3'].astype(np.float32)
    
    # Extract colors (SH coefficients - DC component)
    # f_dc_0, f_dc_1, f_dc_2 are the zeroth-order spherical harmonics
    r = vertex['f_dc_0'].astype(np.float32)
    g = vertex['f_dc_1'].astype(np.float32)
    b = vertex['f_dc_2'].astype(np.float32)
    
    # Extract opacity
    opacity = vertex['opacity'].astype(np.float32)
    
    # Convert SH DC to RGB (0-255)
    SH_C0 = 0.28209479177387814
    colors_r = np.clip((0.5 + SH_C0 * r) * 255, 0, 255).astype(np.uint8)
    colors_g = np.clip((0.5 + SH_C0 * g) * 255, 0, 255).astype(np.uint8)
    colors_b = np.clip((0.5 + SH_C0 * b) * 255, 0, 255).astype(np.uint8)
    
    # Convert opacity (sigmoid)
    alpha = np.clip((1 / (1 + np.exp(-opacity))) * 255, 0, 255).astype(np.uint8)
    
    # Normalize quaternions and convert to uint8
    quat_norm = np.sqrt(rot_0**2 + rot_1**2 + rot_2**2 + rot_3**2)
    rot_0 /= quat_norm
    rot_1 /= quat_norm
    rot_2 /= quat_norm
    rot_3 /= quat_norm
    
    rot_0_u8 = np.clip((rot_0 * 128 + 128), 0, 255).astype(np.uint8)
    rot_1_u8 = np.clip((rot_1 * 128 + 128), 0, 255).astype(np.uint8)
    rot_2_u8 = np.clip((rot_2 * 128 + 128), 0, 255).astype(np.uint8)
    rot_3_u8 = np.clip((rot_3 * 128 + 128), 0, 255).astype(np.uint8)
    
    # Write binary .splat file
    n = len(x)
    with open(output_splat_path, 'wb') as f:
        for i in range(n):
            # Position (3x float32 = 12 bytes)
            f.write(struct.pack('fff', x[i], y[i], z[i]))
            # Scale (3x float32 = 12 bytes)
            f.write(struct.pack('fff', 
                np.exp(scale_0[i]), 
                np.exp(scale_1[i]), 
                np.exp(scale_2[i])))
            # Color + Alpha (4x uint8 = 4 bytes)
            f.write(struct.pack('BBBB', colors_r[i], colors_g[i], colors_b[i], alpha[i]))
            # Rotation (4x uint8 = 4 bytes)
            f.write(struct.pack('BBBB', rot_0_u8[i], rot_1_u8[i], rot_2_u8[i], rot_3_u8[i]))
    
    print(f'Converted {n} Gaussians to .splat ({os.path.getsize(output_splat_path) / 1024 / 1024:.1f} MB)')
    return output_splat_path
