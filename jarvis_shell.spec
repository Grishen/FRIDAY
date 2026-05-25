# -*- mode: python ; coding: utf-8 -*-
# Starter PyInstaller layout for Windows (and cross-build testing).
#
#   pip install pyinstaller
#   pyinstaller jarvis_shell.spec
#
# Output under dist/FridayShell/. Expect to extend hiddenimports when PyInstaller
# misses optional deps (speech_recognition, pyaudio, chromadb, etc.).

block_cipher = None

a = Analysis(
    ['jarvis_shell.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'elevenlabs_tts',
        'jarvis_edge_tts',
        'jarvis_brain',
        'jarvis_actions',
        'jarvis_exceptions',
        'jarvis_system_tools',
        'platform_services',
        'memory.episodic_memory',
        'knowledge.rag_store',
        'knowledge.fs_index',
        'knowledge.embeddings',
        'knowledge.voice_triggers',
        'knowledge.url_ingest',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FridayShell',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FridayShell',
)
