# -*- mode: python ; coding: utf-8 -*-
import glob
import os
from PyInstaller.utils.hooks import collect_all, get_package_paths

datas = []
binaries = []
hiddenimports = []
_sp_base, _ = get_package_paths('sentencepiece')
binaries += [(f, 'sentencepiece.libs') for f in glob.glob(os.path.join(_sp_base, 'sentencepiece.libs', '*.dll'))]
tmp_ret = collect_all('argostranslate')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('langdetect')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['pdf_translator.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torchvision', 'torchaudio', 'matplotlib', 'IPython'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PDF-Translator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
argos_models = Tree('models/argos', prefix='models/argos')
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    argos_models,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PDF-Translator',
)
