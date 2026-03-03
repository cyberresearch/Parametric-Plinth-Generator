# Parametric Plinth Generator

Blender addon for generating parametric plinth geometry for resin printing workflows.

## Current baseline
- Source: `addon/plinth_generator_v3_3.py`
- Blender target: 5.0

## New Install (First Time)
1. Open Blender.
2. Go to `Edit > Preferences > Add-ons`.
3. Click `Install...` and select `addon/plinth_generator_v3_3.py`.
4. Enable the addon.
5. Open the 3D View sidebar (`N`) and find the `Plinth v3.3` tab.

## Update Existing Install
1. Save your current `.blend` file.
2. In Blender, go to `Edit > Preferences > Add-ons`.
3. Search for `Plinth` and disable the currently installed version.
4. Click the down arrow on the addon entry and choose `Remove` (if shown).
5. Click `Install...` and select the new `addon/plinth_generator_v3_3.py`.
6. Re-enable the addon.
7. Reopen your `.blend` file and run `Force Rebuild` once to refresh generated geometry.
