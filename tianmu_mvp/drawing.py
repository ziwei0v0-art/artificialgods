"""Small, replaceable Tk canvas primitives for the first playable prototype."""


def draw_daoist(canvas, x, y, scale=1.0, phase=0.0):
    """Draw one temporary chibi attendant respecting the confirmed silhouette."""
    s = scale
    bob = 2 * phase
    # Long pointed ears sit behind the head.
    canvas.create_polygon(x - 20*s, y - 75*s, x - 55*s, y - 93*s,
                          x - 42*s, y - 58*s, fill="#514e57", outline="#37343b", width=2)
    canvas.create_polygon(x + 20*s, y - 75*s, x + 55*s, y - 93*s,
                          x + 42*s, y - 58*s, fill="#514e57", outline="#37343b", width=2)
    # A compact, dark robe; ordinary flat cloth belt.
    canvas.create_polygon(x - 25*s, y - 46*s + bob, x + 25*s, y - 46*s + bob,
                          x + 42*s, y + 28*s + bob, x - 42*s, y + 28*s + bob,
                          fill="#211f24", outline="#141316", width=2)
    canvas.create_polygon(x - 8*s, y - 46*s + bob, x + 7*s, y - 46*s + bob,
                          x + 17*s, y - 25*s + bob, x - 17*s, y - 25*s + bob,
                          fill="#e4e0d8", outline="")
    canvas.create_rectangle(x - 29*s, y - 9*s + bob, x + 29*s, y - 2*s + bob,
                            fill="#5b5650", outline="")
    canvas.create_line(x - 4*s, y + 28*s + bob, x - 9*s, y + 48*s + bob,
                       fill="#211f24", width=9*s, capstyle="round")
    canvas.create_line(x + 4*s, y + 28*s + bob, x + 9*s, y + 48*s + bob,
                       fill="#211f24", width=9*s, capstyle="round")
    canvas.create_oval(x - 19*s, y + 43*s + bob, x - 2*s, y + 51*s + bob,
                       fill="#18171a", outline="")
    canvas.create_oval(x + 2*s, y + 43*s + bob, x + 19*s, y + 51*s + bob,
                       fill="#18171a", outline="")
    # Face and hands share the same charcoal-gray skin.
    canvas.create_oval(x - 27*s, y - 99*s + bob, x + 27*s, y - 46*s + bob,
                       fill="#514e57", outline="#37343b", width=2)
    canvas.create_oval(x - 37*s, y - 3*s + bob, x - 24*s, y + 11*s + bob,
                       fill="#514e57", outline="")
    canvas.create_oval(x + 24*s, y - 3*s + bob, x + 37*s, y + 11*s + bob,
                       fill="#514e57", outline="")
    # Small white topknot and swept-back cap leave the forehead clear.
    canvas.create_oval(x - 19*s, y - 108*s + bob, x + 19*s, y - 78*s + bob,
                       fill="#f1eee7", outline="#d2cec5", width=1)
    canvas.create_oval(x - 8*s, y - 122*s + bob, x + 9*s, y - 105*s + bob,
                       fill="#f5f2eb", outline="#d2cec5", width=1)
    canvas.create_line(x - 16*s, y - 72*s + bob, x + 16*s, y - 72*s + bob,
                       fill="#dfd9d0", width=3*s, capstyle="round")
    canvas.create_oval(x - 12*s, y - 77*s + bob, x - 7*s, y - 72*s + bob,
                       fill="#a7474d", outline="")
    canvas.create_oval(x + 7*s, y - 77*s + bob, x + 12*s, y - 72*s + bob,
                       fill="#a7474d", outline="")
    canvas.create_line(x - 3*s, y - 60*s + bob, x + 3*s, y - 60*s + bob,
                       fill="#332d31", width=1)


def draw_shrine(canvas, x, y, scale=1.0, plate=False):
    """Draw a simple shrine and a static six-armed idol silhouette."""
    s = scale
    canvas.create_polygon(x - 85*s, y - 100*s, x, y - 148*s, x + 85*s, y - 100*s,
                          fill="#78634d", outline="#463929", width=3)
    canvas.create_rectangle(x - 67*s, y - 101*s, x + 67*s, y + 5*s,
                            fill="#8f7659", outline="#463929", width=3)
    canvas.create_rectangle(x - 48*s, y - 81*s, x + 48*s, y - 30*s,
                            fill="#322b28", outline="#be9d70", width=2)
    # Six arms distinguish the static icon; this is an icon-sized placeholder.
    for dy, dx in [(-62, -47), (-44, -59), (-27, -49), (-62, 47), (-44, 59), (-27, 49)]:
        canvas.create_line(x, y - 69*s, x + dx*s, y + dy*s,
                           fill="#d3b98e", width=3*s, capstyle="round")
    canvas.create_polygon(x - 10*s, y - 87*s, x - 31*s, y - 95*s,
                          x - 24*s, y - 77*s, fill="#b9a680", outline="#554731")
    canvas.create_polygon(x + 10*s, y - 87*s, x + 31*s, y - 95*s,
                          x + 24*s, y - 77*s, fill="#b9a680", outline="#554731")
    canvas.create_oval(x - 14*s, y - 91*s, x + 14*s, y - 63*s,
                       fill="#b9a680", outline="#554731", width=2)
    canvas.create_polygon(x - 78*s, y + 5*s, x + 78*s, y + 5*s,
                          x + 96*s, y + 22*s, x - 96*s, y + 22*s,
                          fill="#644e39", outline="#463929", width=2)
    tray_width = 29 if plate else 21
    tray_fill = "#e4d7b9" if plate else "#886c4f"
    canvas.create_oval(x - tray_width*s, y - 7*s, x + tray_width*s, y + 5*s,
                       fill=tray_fill, outline="#9f8e6f")
    for offset in (-10, 0, 10):
        canvas.create_oval(x + offset*s - 4*s, y - 9*s,
                           x + offset*s + 4*s, y - 2*s,
                           fill="#a84f40", outline="")
