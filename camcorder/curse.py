import curses

def main(sc):
    sc.clear()

    screen = sc.subwin(23, 79, 0, 0)
    screen.box()
    screen.hline(2, 1, curses.ACS_HLINE, 77)

    status = None
    fps = 0.0
    vid_size = (0, 0)

    screen.addstr(1, 1, 'Status: {}'.format('None'))
    screen.refresh()


    # for i in range(10):
    #     sc.addstr(i, 0, str(i))

    #sc.refresh()
    curses.echo()
    sc.getstr()

curses.wrapper(main)