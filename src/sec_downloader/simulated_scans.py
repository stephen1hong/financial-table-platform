"""Reproducible image-only PDFs made from reviewed source pages; no OCR or gold data."""
import argparse
import importlib.metadata
import json
from pathlib import Path

import pdfplumber
from PIL import Image
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader

from .downloader import RAW_DIR, compute_sha256, verify_cached_file


def generate(recipe_path='tests/fixtures/scan_recipe.json', output_dir='data/processed/ocr/scans'):
    recipe = json.loads(Path(recipe_path).read_text())
    source = RAW_DIR / recipe['source_filename']
    if not verify_cached_file(source, recipe['source_sha256']):
        raise ValueError('Original PDF checksum does not match the reviewed scan recipe')
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    with pdfplumber.open(source) as pdf:
        for variant in recipe['variants']:
            for n in recipe['pages']:
                page = pdf.pages[n-1]
                img = page.to_image(resolution=variant['dpi']).original.convert('RGB')
                if variant['rotation_degrees']:
                    img = img.rotate(variant['rotation_degrees'], resample=Image.Resampling.BICUBIC,
                                     expand=False, fillcolor='white')
                stem = f"{variant['id']}-page-{n}"
                png, scan = out/(stem+'.png'), out/(stem+'.pdf')
                img.save(png)
                canvas = Canvas(str(scan), pagesize=(page.width, page.height), invariant=1, pageCompression=1)
                canvas.setTitle('Simulated scan: ' + stem)
                canvas.drawImage(ImageReader(img), 0, 0, width=page.width, height=page.height)
                canvas.showPage()
                canvas.save()
                with pdfplumber.open(scan) as check:
                    if check.pages[0].chars or not check.pages[0].images:
                        raise ValueError('Simulated scan must have an image and no PDF text')
                records.append({**variant, 'label': 'simulated_scan', 'source_document': source.as_posix(),
                    'source_sha256': recipe['source_sha256'], 'original_page': n, 'scan_page': 1,
                    'page_width': page.width, 'page_height': page.height, 'image_size': list(img.size),
                    'image': png.as_posix(), 'image_sha256': compute_sha256(png),
                    'pdf': scan.as_posix(), 'pdf_sha256': compute_sha256(scan)})
    manifest = {'recipe': recipe, 'versions': {p: importlib.metadata.version(p) for p in ('pdfplumber','pypdfium2','Pillow','reportlab')}, 'scans': records}
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recipe', default='tests/fixtures/scan_recipe.json')
    p.add_argument('--output-dir', default='data/processed/ocr/scans')
    args = p.parse_args()
    result = generate(args.recipe, args.output_dir)
    print(f"Generated {len(result['scans'])} simulated image-only PDFs: {args.output_dir}/manifest.json")


if __name__ == '__main__':
    main()
