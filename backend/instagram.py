"""Instagram data provider for Instafeed.

- search_users():  multi-strategy handle search:
      1. anonymous web topsearch (works from most home IPs)
      2. logged-in search via instaloader session (when INSTAGRAM_LOGIN is set)
