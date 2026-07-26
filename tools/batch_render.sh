#!/bin/bash
# batch_render.sh — Render all 18 units in sequence using fast mode.
# Each render takes ~2-3 min at 16 Cycles samples.
# Total: ~45-60 min for all 18 units.
# Run from project root: bash tools/batch_render.sh

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

UNITS=(
    # Iron Directorate (9)
    "iron_directorate_line_infantry"
    "iron_directorate_command_officer"
    "iron_directorate_pathfinder_scout"
    "iron_directorate_storm_talons"
    "iron_directorate_ashrim_raiders"
    "iron_directorate_suppression_team"
    "iron_directorate_ironclad_warden"
    "iron_directorate_logistics_engineer"
    "iron_directorate_ironclad_high_command"
    # Cinderborn (9)
    "cinderborn_cinder_cultist"
    "cinderborn_voidtouched_legionnaire"
    "cinderborn_cinder_wraith"
    "cinderborn_soul_weaver"
    "cinderborn_ashbound_artificer"
    "cinderborn_zealot_captain"
    "cinderborn_son_of_ciner"
    "cinderborn_ash_stalker"
    "cinderborn_warlord"
    # Parasitic Bloom (2)
    "parasitic_bloom_bloated_swarm"
    "parasitic_bloom_toxic_reaver"
    # Harmonic Collective (2)
    "harmonic_collective_precision_drone"
    "harmonic_collective_logic_weaver"
    # Chrono Revenants (2)
    "chrono_revenants_time_soldier"
    "chrono_revenants_chrono_guardian"
    # Wreckstorm Clans (2)
    "wreckstorm_clans_wreck_raider"
    "wreckstorm_clans_scrap_boss"
    # Void Corsairs (2)
    "void_corsairs_void_raider"
    "void_corsairs_shadow_blade"
    # Vehicles (3)
    "iron_directorate_predator_tank"
    "wreckstorm_clans_battle_wagon"
    "harmonic_collective_gun_drone"
    # Creature (1)
    "parasitic_bloom_swarm_beast"
    # Insectoids (2)
    "chrono_revenants_chrono_scarab"
    "void_corsairs_shade_swarm"
)

TOTAL=${#UNITS[@]}
COUNT=0

for UNIT in "${UNITS[@]}"; do
    COUNT=$((COUNT + 1))
    echo ""
    echo "========================================"
    echo "[$COUNT/$TOTAL] Rendering: $UNIT"
    echo "========================================"
    
    # Find the .blend file — prefer model/*v2.blend
    BLEND=$(find "$PROJECT_ROOT/assets/units/$UNIT/model" -name "*.blend" 2>/dev/null | head -1)
    
    if [ -z "$BLEND" ]; then
        echo "  WARNING: No .blend found for $UNIT, skipping"
        continue
    fi
    
    # Remove old renders
    rm -rf "$(dirname "$BLEND")/render/raw"
    
    echo "  Blend: $BLEND"
    echo "  Started: $(date)"
    
    # Render with fast mode (16 samples Cycles)
    blender --background "$BLEND" \
        --python "$PROJECT_ROOT/tools/blender/render_8dir_v2.py" \
        -- --engine CYCLES --fast 2>&1 | tail -1
    
    echo "  Finished: $(date)"
    
    # Quick critic check
    RAW_DIR="$(dirname "$BLEND")/render/raw"
    if [ -d "$RAW_DIR" ]; then
        python3 "$PROJECT_ROOT/tools/critic.py" "$RAW_DIR" 2>&1 | grep -E "PASS|FAIL|frames"
    fi
done

echo ""
echo "========================================"
echo "Batch render complete: $COUNT/$TOTAL units"
echo "Now run: PIPELINE_VERSION=v0.4.0 python3 tools/batch_pipeline.py"
echo "========================================"
