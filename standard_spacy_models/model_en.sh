#*************************************
# SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
# SPDX-License-Identifier: AGPL-3.0-only 
#************************************/


# download en model
curl -LJO https://github.com/explosion/spacy-models/releases/download/en_core_web_md-2.3.0/en_core_web_md-2.3.0.tar.gz
# extract tar.gz
tar -zxvf en_core_web_md-2.3.0.tar.gz
rm en_core_web_md-2.3.0.tar.gz