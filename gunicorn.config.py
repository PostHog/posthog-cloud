#!/usr/bin/env python3
# -*- coding: utf-8 -*-	# -*- coding: utf-8 -*-




loglevel = "error"	loglevel = "error"
bind = "unix://tmp/nginx.socket"
worker_class = "gevent"
timeout = 90




def on_starting(server):	def on_starting(server):
    print(	    print(
        """	        """
\x1b[1;34m"""	\x1b[1;34m"""
        + r"""	        + r"""
 _____          _   _    _             	 _____          _   _    _             
|  __ \        | | | |  | |            	|  __ \        | | | |  | |            
| |__) |__  ___| |_| |__| | ___   __ _ 	| |__) |__  ___| |_| |__| | ___   __ _ 
|  ___/ _ \/ __| __|  __  |/ _ \ / _` |	|  ___/ _ \/ __| __|  __  |/ _ \ / _` |
| |  | (_) \__ \ |_| |  | | (_) | (_| |	| |  | (_) \__ \ |_| |  | | (_) | (_| |
|_|   \___/|___/\__|_|  |_|\___/ \__, |	|_|   \___/|___/\__|_|  |_|\___/ \__, |
                                  __/ |	                                  __/ |
                                 |___/ 	                                 |___/ 
"""	"""
        + """	        + """
\x1b[0m	\x1b[0m
"""	"""
    )	    )
    print("Server running on \x1b[4mhttp://{}:{}\x1b[0m".format(*server.address[0]))	    print("Server running on \x1b[4mhttp://{}:{}\x1b[0m".format(*server.address[0]))
    print("Questions? Please shoot us an email at \x1b[4mhey@posthog.com\x1b[0m")	    print("Questions? Please shoot us an email at \x1b[4mhey@posthog.com\x1b[0m")
    print("\nTo stop, press CTRL + C")	    print("\nTo stop, press CTRL + C")


def when_ready(server):
    open("/tmp/app-initialized", "w").close()
