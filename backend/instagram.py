"""Instagram data provider for Instafeed.

- search_users():  multi-strategy handle search:
      1. anonymous web topsearch (works from most home IPs)
      2. logged-in search via instaloader session (when INSTAGRAM_LOGIN is set)
      3. exact-handle match via public profile fetch (search blocked, profile OK)
- get_profile():   instaloader public profile metadata.
- get_videos():    instaloader — walks every post of a public profile and
                   keeps only video posts (reels / video posts).
