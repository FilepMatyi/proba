import pycolmap
import os
import shutil

def run_colmap(image_dir, output_dir):
    """Run COLMAP sparse reconstruction on CPU."""
    os.makedirs(output_dir, exist_ok=True)
    db_path = os.path.join(output_dir, 'database.db')
    sparse_dir = os.path.join(output_dir, 'sparse')
    os.makedirs(sparse_dir, exist_ok=True)
    
    # Feature extraction (CPU)
    pycolmap.extract_features(
        database_path=db_path,
        image_path=image_dir,
        camera_mode=pycolmap.CameraMode.AUTO,
        sift_options=pycolmap.SiftExtractionOptions(use_gpu=False)
    )
    
    # Feature matching (exhaustive, CPU)
    pycolmap.match_exhaustive(
        database_path=db_path,
        sift_options=pycolmap.SiftMatchingOptions(use_gpu=False)
    )
    
    # Sparse reconstruction
    maps = pycolmap.incremental_mapping(
        database_path=db_path,
        image_path=image_dir,
        output_path=sparse_dir
    )
    
    if not maps:
        raise RuntimeError('COLMAP reconstruction failed - no maps produced')
    
    # Use the largest reconstruction
    best_map = max(maps, key=lambda m: m.num_reg_images())
    
    return sparse_dir, best_map

def run_opensplat(colmap_dir, image_dir, output_path, num_iters=7000):
    """Run OpenSplat 3DGS training."""
    import subprocess
    
    cmd = [
        'opensplat',
        colmap_dir,
        '--output', output_path,
        '--num-iters', str(num_iters),
        '--num-downscales', '2',  # Reduce resolution for CPU speed
        '-n', '1'  # Single thread for CPU
    ]
    
    print(f'Running OpenSplat: {" ".join(cmd)}')
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=86400)  # 24h timeout
    
    if result.returncode != 0:
        raise RuntimeError(f'OpenSplat failed: {result.stderr}')
    
    return output_path

def reconstruct_3d(vehicle_id, image_paths, work_dir='/tmp/3d-work'):
    """
    Full 3D reconstruction pipeline.
    
    Args:
        vehicle_id: Vehicle identifier
        image_paths: List of local file paths to input images
        work_dir: Working directory for intermediate files
    
    Returns:
        str: Path to the output .splat file
    """
    import os
    
    # 1. Run COLMAP
    colmap_output = os.path.join(work_dir, 'colmap')
    sparse_dir, best_map = run_colmap(image_paths, colmap_output)
    print(f'COLMAP sparse reconstruction finished. Images registered: {best_map.num_reg_images()}')
    
    # 2. Run OpenSplat
    splat_output_dir = os.path.join(work_dir, 'opensplat')
    os.makedirs(splat_output_dir, exist_ok=True)
    run_opensplat(sparse_dir, image_paths, splat_output_dir)
    
    # 3. Convert .ply to .splat
    from processing.splat_converter import ply_to_splat
    ply_path = os.path.join(splat_output_dir, 'splat.ply') # OpenSplat defaults to output.ply or splat.ply? Usually it creates point_cloud/iteration_7000/point_cloud.ply. Wait, opensplat args: --output output_path creates splat.ply?
    # Actually, standard OpenSplat or Gaussian Splatting creates point_cloud.ply or similar, but the user snippet just passes `--output output_path` which might be a directory or file.
    # Let's assume opensplat creates `splat.ply` inside `output_path` directory or `output_path` itself is the file.
    # We will search for a .ply file in the output dir if it's a dir, or assume it's splat.ply.
    
    final_splat = os.path.join(work_dir, 'model.splat')
    
    # Let's check what `--output output_path` does. Usually it creates a directory.
    # If it is a directory, the ply is at `point_cloud/iteration_7000/point_cloud.ply`
    # We will use a generic search for .ply in output_path to be safe.
    ply_files = []
    for root, dirs, files in os.walk(splat_output_dir):
        for f in files:
            if f.endswith('.ply'):
                ply_files.append(os.path.join(root, f))
    
    if not ply_files:
        raise RuntimeError('No .ply file found from OpenSplat')
    
    # Convert the first found .ply
    ply_to_splat(ply_files[0], final_splat)
    
    return final_splat
