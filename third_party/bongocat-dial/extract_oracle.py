#!/usr/bin/env python3
"""Emit a standalone oracle whose algorithms are the pinned, unmodified C bodies."""
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'upstream/src/ui/dial'


def function(file, name):
    text = (SOURCE / file).read_text()
    match = re.search(r'^(?:static )?[^\n;]+\b' + name + r'\([^;]*?\)\s*\{', text, re.M)
    if not match:
        raise ValueError(f'Missing pinned function {file}:{name}')
    start, depth = match.start(), 1
    index = match.end()
    while depth:
        depth += (text[index] == '{') - (text[index] == '}')
        index += 1
    return text[start:index] + '\n'


def generate():
    header = (SOURCE / 'dial_internal.h').read_text()
    constants = '\n'.join(line for line in header.splitlines() if line.startswith('#define DIAL_'))
    types = header[header.index('typedef struct DialPoint'):header.index('typedef struct DialItem')]
    geometry = (SOURCE / 'dial_geometry.c').read_text().replace('#include "dial_internal.h"', '', 1)
    root_angle = re.search(r'float angle = ([^;]+);', (SOURCE / 'dial_paint.c').read_text()).group(1)
    return '\n'.join([
        '/* Generated test-only adapter. Original algorithms below retain AGPL-3.0-only provenance. */',
        '#include <math.h>\n#include <stdbool.h>\n#include <stdint.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>',
        constants, types,
        '''typedef struct DialItem { size_t children; } DialItem;
typedef struct DialPaint {
    DialPath roots[DIAL_ROOTS], children[DIAL_PAGE];
    int child_path_count, child_path_active, child_path_roots;
    float child_path_step, zoom, offset_x, offset_y;
} DialPaint;
typedef struct Dial {
    int count, active, child, page, width, height;
    bool child_focus, dirty;
    float opening, scale, lift[DIAL_ROOTS];
    uint64_t animation_at, opened_at, changed_at;
    DialItem items[DIAL_ROOTS];
    DialPaint paint;
} Dial;''',
        function('dial_items.c', 'dial_child_count'),
        function('dial_items.c', 'dial_child_step'),
        function('dial_items.c', 'dial_child_angle'), geometry,
        function('dial_input.c', 'pointer'),
        function('dial_scene.c', 'reveal'),
        function('dial_window.c', 'animate'),
        'static float original_root_angle(int i, Dial *d) { return ' + root_angle + '; }',
        r'''int main(void) {
    char line[512], op;
    while (fgets(line, sizeof(line), stdin)) {
        if (sscanf(line, " %c", &op) != 1) continue;
        Dial d = {0}; d.scale = d.opening = 1;
        if (op == 'S') {
            float inner, outer, a, b; sscanf(line+1,"%f %f %f %f",&inner,&outer,&a,&b);
            DialPath p; dial_sector(&p,inner,outer,a,b);
            printf("%d",p.count);
            for (int i=0;i<p.count;i++) printf(" %.9g %.9g",p.points[i].x,p.points[i].y);
        } else if (op == 'A') {
            int i; sscanf(line+1,"%d %d",&i,&d.count); printf("%.9g",original_root_angle(i,&d));
        } else if (op == 'C') {
            int n,i; sscanf(line+1,"%d %d %d %d",&d.active,&d.count,&n,&i);
            d.items[d.active].children=n; printf("%.9g %.9g",dial_child_step(&d),dial_child_angle(&d,i));
        } else if (op == 'H' || op == 'P') {
            int n,focus,click=0,root,child;float x,y;
            sscanf(line+1,"%d %d %d %d %f %f %d",&d.count,&d.active,&n,&focus,&x,&y,&click);
            if(d.active>=0)d.items[d.active].children=n;d.child_focus=focus;
            if(op=='P')pointer(&d,x,y,click,&root,&child); else dial_hit(&d,x,y,&root,&child);
            printf("%d %d %d",root,child,d.child_focus);
        } else if (op == 'R') {
            unsigned long long ms;int i;sscanf(line+1,"%llu %d",&ms,&i);printf("%.9g",reveal(ms,0,i));
        } else if (op == 'M') {
            float current;int target;unsigned long long ms;
            sscanf(line+1,"%f %d %llu",&current,&target,&ms);
            d.count=1;d.active=target?0:-1;d.lift[0]=current;animate(&d,ms);printf("%.9g",d.lift[0]);
        } else if (op == 'O') {
            unsigned long long ms;sscanf(line+1,"%llu",&ms);d.active=-1;animate(&d,ms);printf("%.9g",d.opening);
        } else return 2;
        puts("");
    }
    return 0;
}'''])


if __name__ == '__main__':
    output = generate()
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(output)
    else:
        print(output)
