import multiprocessing
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == '--restore':
        sys.argv.pop(1)
        from timelabs.maintenance import main
        main()
    else:
        from timelabs.ui import main
        sys.exit(main())
