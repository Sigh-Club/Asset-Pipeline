#!/bin/bash
# HQ emote extraction: border key -> pocket fills -> black-backed defringe -> alpha clean -> 128px
set -e
cd /home/talzanar/Downloads/mtc_emotes
SRC=/home/talzanar/Downloads/faafc0c2-af86-4efd-ab74-520215a6a9f4.jpeg
names=(hype hi gg lol rip love rage wtf)
i=0
for row in 0 1; do
for col in 0 1 2 3; do
  x=$((col*256)); y=$((row*286)); n=${names[$i]}; i=$((i+1))
  magick "$SRC" -crop 256x286+$x+$y +repage cells/${n}_raw.png

  # 1. key the outer background (corners + edge midpoints), fuzz 15%
  magick cells/${n}_raw.png -alpha set -fuzz 15% -fill none \
    -draw 'alpha 0,0 floodfill'   -draw 'alpha 255,0 floodfill' \
    -draw 'alpha 0,285 floodfill' -draw 'alpha 255,285 floodfill' \
    -draw 'alpha 127,0 floodfill' -draw 'alpha 127,285 floodfill' \
    -draw 'alpha 0,142 floodfill' -draw 'alpha 255,142 floodfill' \
    cells/${n}_stage.png

  # 2. detect enclosed white pockets, fill each.
  #    default: badge zone (top 35% of cell), area>=10.
  #    wtf: full cell, area>=50 (big pockets behind the arms; keeps teeth/shirt detail).
  if [ "$n" = wtf ]; then ZMAX=100; AMIN=50; else ZMAX=35; AMIN=10; fi
  magick cells/${n}_stage.png -background black -alpha remove -alpha off \
    -colorspace gray -threshold 85% cells/${n}_mask.png
  mapfile -t pts < <(magick cells/${n}_mask.png \
    -define connected-components:verbose=true \
    -define connected-components:area-threshold=$AMIN -connected-components 8 null: 2>/dev/null \
    | grep 'gray(255)' | awk -v H=286 -v Z=$ZMAX \
    '{n=split($2,p,"+"); split($3,c,","); if (c[2]>0 && 100*c[2]/H<Z && $4+0>=AMIN) printf "%d %d\n", int(c[1]), int(c[2])}')
  if [ ${#pts[@]} -gt 0 ]; then
    draw=()
    for pt in "${pts[@]}"; do set -- $pt; draw+=(-draw "alpha $1,$2 floodfill"); done
    magick cells/${n}_stage.png -fuzz 8% -fill none "${draw[@]}" cells/${n}_stage.png
  fi
  echo "$n: pockets filled at [${pts[*]:-none}]"

  # 3. defringe (black-backed): transparent pixels' RGB -> black, then every bright
  #    pixel within 2px of a dark/translucent region is recoloured to the local
  #    darkest colour. Kills stroke specks AND the light JPEG band hugging outlines.
  magick cells/${n}_stage.png -background black -alpha background cells/${n}_bb.png
  magick cells/${n}_bb.png -channel RGB -statistic minimum 3x3 cells/${n}_min.png
  magick cells/${n}_bb.png -colorspace gray -threshold 72% cells/${n}_bright.png
  magick cells/${n}_bb.png -colorspace gray -threshold 22% -negate \
    -morphology Dilate Diamond:2 cells/${n}_darkd.png
  magick cells/${n}_bright.png cells/${n}_darkd.png -compose Multiply -composite cells/${n}_cand.png
  magick cells/${n}_min.png cells/${n}_bb.png cells/${n}_cand.png -composite cells/${n}_defr.png

  # 4. alpha cleanup: 1px erode + harden partial alpha (kills residual halo ring)
  magick cells/${n}_defr.png -channel A -morphology Erode Diamond:1 +channel \
    -channel A -level 50%,100% +channel cells/${n}_clean.png
done
done

# 5. preview at full size on Discord-dark for individual inspection
montage cells/hype_clean.png cells/hi_clean.png cells/gg_clean.png cells/lol_clean.png \
        cells/rip_clean.png cells/love_clean.png cells/rage_clean.png cells/wtf_clean.png \
        -tile 2x4 -geometry +12+12 -background '#2b2d31' inspect_clean.png
echo done
