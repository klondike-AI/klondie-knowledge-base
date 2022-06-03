#*************************************
# SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
# SPDX-License-Identifier: AGPL-3.0-only 
#************************************/

FROM rasa/rasa:2.0.6-full
USER root
RUN apt-get update --allow-releaseinfo-change
RUN apt-get -y install libpq-dev
RUN apt-get update
RUN pip install -U spacy==2.3.2
RUN apt-get install -y curl
RUN apt-get update
RUN apt-get install -y python3-pip
RUN apt-get install -y python3-dev default-libmysqlclient-dev build-essential
RUN pip3 install mysqlclient
RUN apt-get install -y python3-mysqldb
RUN pip3 install mysql-connector-python
RUN apt-get update
RUN pip3 install nest_asyncio
RUN pip3 install requests
RUN pip3 install redis
RUN apt-get install -y ruby
RUN apt-get install -y ruby-dev build-essential
RUN gem install sequel
RUN gem install mysql2
RUN apt-get install lsof
RUN apt-get install -y expect
ENTRYPOINT tail -f /dev/null
