#*************************************
# SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
# SPDX-License-Identifier: AGPL-3.0-only 
#************************************/


#!/bin/bash

port_cors=
port_action=

kill -9 $(lsof -t -i:$port_cors) 2>&1 &
kill -9 $(lsof -t -i:$port_action) 2>&1 &

rasa run --cors "*" -p $port_cors >/dev/null 2>&1 &
rasa run actions -p $port_action >/dev/null 2>&1 &