"""Automatic polling pipeline for Instafeed.


The core loop mirrors a classic cron job:

    for each subscribed user:
        fetch their LATEST videos only (default 10)      # fast, rate-limit friendly
        insert only the ones we don't already have       # dedupe by video id
    frontend just reads the DB, newest first             # nothing new -> nothing changes
