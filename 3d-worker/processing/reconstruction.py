import os
import shutil
import subprocess
import tempfile
import time
import pycolmap
from PIL import Image


def reconstruct_3d(vehicle_id, image_dir, work_dir='/tmp/3d-work'):
    """
    Full 3D Gaussian Splatting reconstruction pipeline.
    
    Pipeline:
    1. COLMAP sparse reconstruction (camera poses + sparse point cloud)
    2. OpenSplat training (3D Gaussian Splatting)
    3. PLY → SPLAT conversion
    
    Args:
        vehicle_id: Vehicle identifier for logging
        image_dir: Directory containing input JPEG images
        work_dir: Working directory for intermediate files
    
    Returns:
        str: Path to the output .splat file
    """
    colmap_dir = os.path.join(work_dir, 'colmap')
    splat_output = os.path.join(work_dir, 'model.ply')
    final_splat = os.path.join(work_dir, 'model.splat')
    
    os.makedirs(colmap_dir, exist_ok=True)
    
    # ── Step 1: COLMAP Sparse Reconstruction ──
    print(f"[{vehicle_id}] Step 1/3: COLMAP sparse reconstruction...")
    start = time.time()
    
    run_colmap(image_dir, colmap_dir)
    
    colmap_time = time.time() - start
    print(f"[{vehicle_id}] COLMAP complete in {colmap_time:.0f}s")
    
    # ── Step 2: OpenSplat 3DGS Training ──
    print(f"[{vehicle_id}] Step 2/3: OpenSplat 3DGS training (CPU, this will take a while)...")
    start = time.time()
    
    num_iters = int(os.environ.get('OPENSPLAT_ITERS', '7000'))
    num_downscales = int(os.environ.get('OPENSPLAT_DOWNSCALES', '2'))
    
    run_opensplat(colmap_dir, image_dir, splat_output, 
                  num_iters=num_iters, num_downscales=num_downscales)
    
    train_time = time.time() - start
    print(f"[{vehicle_id}] OpenSplat training complete in {train_time:.0f}s")
    
    # ── Step 3: PLY → SPLAT Conversion ──
    print(f"[{vehicle_id}] Step 3/3: Converting PLY → SPLAT...")
    
    from processing.splat_converter import ply_to_splat
    ply_to_splat(splat_output, final_splat)
    
    total_time = colmap_time + train_time
    file_size_mb = os.path.getsize(final_splat) / 1024 / 1024
    print(f"[{vehicle_id}] 3D reconstruction complete!")
    print(f"  Total time: {total_time:.0f}s ({total_time/60:.1f} min)")
    print(f"  Output: {final_splat} ({file_size_mb:.1f} MB)")
    
    return final_splat


def run_colmap(image_dir, output_dir):
    """
    Run COLMAP sparse reconstruction on CPU.
    
    This estimates camera poses for each input image using:
    1. SIFT feature extraction (CPU)
    2. Exhaustive feature matching (CPU)
    3. Incremental Structure-from-Motion
    """
    db_path = os.path.join(output_dir, 'database.db')
    sparse_dir = os.path.join(output_dir, 'sparse')
    os.makedirs(sparse_dir, exist_ok=True)
    
    # Count input images
    images = [f for f in os.listdir(image_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    print(f"  COLMAP: Processing {len(images)} images (CPU mode)")
    
    # Feature extraction (SIFT, CPU)
    print("  COLMAP: Extracting features...")
    pycolmap.extract_features(
        database_path=db_path,
        image_path=image_dir,
        camera_mode=pycolmap.CameraMode.AUTO,
        sift_options=pycolmap.SiftExtractionOptions(use_gpu=False)
    )
    
    # Feature matching (exhaustive, CPU)
    print("  COLMAP: Matching features...")
    pycolmap.match_exhaustive(
        database_path=db_path,
        sift_options=pycolmap.SiftMatchingOptions(use_gpu=False)
    )
    
    # Incremental SfM
    print("  COLMAP: Running incremental mapping...")
    maps = pycolmap.incremental_mapping(
        database_path=db_path,
        image_path=image_dir,
        output_path=sparse_dir
    )
    
    if not maps:
        raise RuntimeError(
            'COLMAP reconstruction failed - no maps produced. '
            'This usually means the images don\'t have enough overlap or features.'
        )
    
    # Find the best reconstruction (most registered images)
    best_idx = 0
    best_count = 0
    for idx, recon in maps.items():
        num_images = recon.num_reg_images()
        print(f"  COLMAP: Map {idx}: {num_images} registered images, "
              f"{recon.num_points3D()} 3D points")
        if num_images > best_count:
            best_count = num_images
            best_idx = idx
    
    print(f"  COLMAP: Using map {best_idx} with {best_count} images")
    
    # Write the best reconstruction in COLMAP text format
    # (OpenSplat reads COLMAP format directly)
    best_sparse = os.path.join(sparse_dir, '0')
    os.makedirs(best_sparse, exist_ok=True)
    maps[best_idx].write(best_sparse)
    
    return sparse_dir


def run_opensplat(colmap_dir, image_dir, output_path, num_iters=7000, num_downscales=2):
    """
    Run OpenSplat 3DGS training on CPU.
    
    OpenSplat reads COLMAP output format and produces a .ply file
    containing the trained 3D Gaussians.
    
    Args:
        colmap_dir: Directory containing COLMAP sparse reconstruction
        image_dir: Directory containing input images
        output_path: Path for output .ply file
        num_iters: Number of training iterations (default 7000, reduce for speed)
        num_downscales: Number of times to halve image resolution (2 = 1/4 res)
    """
    # OpenSplat expects a project directory with:
    # - sparse/0/ (COLMAP output)
    # - images/ (input images)
    # We create symlinks to avoid copying
    
    project_dir = os.path.join(os.path.dirname(output_path), 'opensplat_project')
    os.makedirs(project_dir, exist_ok=True)
    
    # Link sparse dir
    sparse_link = os.path.join(project_dir, 'sparse')
    if os.path.exists(sparse_link):
        os.remove(sparse_link) if os.path.islink(sparse_link) else shutil.rmtree(sparse_link)
    os.symlink(os.path.join(colmap_dir, 'sparse'), sparse_link)
    
    # Link images
    images_link = os.path.join(project_dir, 'images')
    if os.path.exists(images_link):
        os.remove(images_link) if os.path.islink(images_link) else shutil.rmtree(images_link)
    os.symlink(image_dir, images_link)
    
    cmd = [
        'opensplat', project_dir,
        '--output', output_path,
        '--num-iters', str(num_iters),
        '--num-downscales', str(num_downscales),
        '-n', '1',  # Single thread for CPU stability
    ]
    
    print(f"  OpenSplat: Running with {num_iters} iterations, {num_downscales} downscales")
    print(f"  OpenSplat: Command: {' '.join(cmd)}")
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    # Stream output for progress monitoring
    last_report = time.time()
    for line in process.stdout:
        line = line.strip()
        if line:
            # Only print progress every 30 seconds to avoid log spam
            now = time.time()
            if now - last_report > 30 or 'iter' in line.lower() or 'error' in line.lower():
                print(f"  OpenSplat: {line}")
                last_report = now
    
    process.wait()
    
    if process.returncode != 0:
        raise RuntimeError(f'OpenSplat failed with exit code {process.returncode}')
    
    if not os.path.exists(output_path):
        raise RuntimeError(f'OpenSplat did not produce output file: {output_path}')
    
    file_size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"  OpenSplat: Output PLY: {file_size_mb:.1f} MB")
