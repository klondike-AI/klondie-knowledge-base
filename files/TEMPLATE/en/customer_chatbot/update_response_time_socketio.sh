#*************************************
# SPDX-FileCopyrightText: 2009-2020 Vtenext S.r.l. <info@vtenext.com> and KLONDIKE S.r.l. <info@klondike.ai> 
# SPDX-License-Identifier: AGPL-3.0-only 
#************************************/


#!/bin/bash

redis_connections=$(head -n 1 ../db_connections/REDIS_CONNECTIONS.json)

#################################################################################################
# AUMENTA IL TEMPO MASSIMO CHE IL CHATBOT HA A DISPOSIZIONE PER FORNIRE ALL'UTENTE UNA RISPOSTA #
#################################################################################################

# cd alla root
cd /

# cerca il file console.py a partire dalla root e tiene solo il risultato contenente il percorso 'rasa/core/channels/console.py'
filename="$(find . -type f -name console.py 2>&1 | grep -e 'rasa/core/channels/console.py')"

# scorre i tutti i file trovati e sostituisce n1 secondi con n2 secondi
for file in $(echo $filename | tr " " "\n"); do
  sed -i 's/DEFAULT_STREAM_READING_TIMEOUT_IN_SECONDS = 10/DEFAULT_STREAM_READING_TIMEOUT_IN_SECONDS = 600/' $file
done


############################################################################################
# AGGIORNA IL FILE processor.py AFFINCHE' NON DIA ERRORE PER I LOOP INFINITI CON LE AZIONI #
############################################################################################

# cerca il file processor.py a partire dalla root e tiene solo il risultato contenente il percorso 'rasa/core/channels/processor.py'
filename="$(find . -type f -name processor.py 2>&1 | grep -e 'processor.py')"

sed -i 's/"MAX_NUMBER_OF_PREDICTIONS", "10"/"MAX_NUMBER_OF_PREDICTIONS", "9999999"/' $filename


################################################################################################
# AGGIORNA IL FILE socketio.py  PER LA GESTIONE DELLA CHAT CON UN OPERATORE UMANO (ASSISTENZA) #
################################################################################################

# cerca il file socketio.py a partire dalla root e tiene solo il risultato contenente il percorso 'rasa/core/channels/socketio.py'
filename="$(find . -type f -name socketio.py 2>&1 | grep -e 'rasa/core/channels/socketio.py')"

#rimuove il file vecchio
rm $filename

redis_ip=$(echo $redis_connections| cut -d'"' -f 2)
redis_port=$(echo $redis_connections| cut -d':' -f 3| cut -d'}' -f 1)

cat > $filename << EOF
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Text

from rasa.core.channels.channel import InputChannel, OutputChannel, UserMessage
import rasa.shared.utils.io
from sanic import Blueprint, response
from sanic.request import Request
from sanic.response import HTTPResponse
from socketio import AsyncServer
import redis
import time


logger = logging.getLogger(__name__)


class SocketBlueprint(Blueprint):
    def __init__(self, sio: AsyncServer, socketio_path, *args, **kwargs):
        self.sio = sio
        self.socketio_path = socketio_path
        super().__init__(*args, **kwargs)

    def register(self, app, options) -> None:
        self.sio.attach(app, self.socketio_path)
        super().register(app, options)


class SocketIOOutput(OutputChannel):
    @classmethod
    def name(cls) -> Text:
        return "socketio"

    def __init__(self, sio: AsyncServer, bot_message_evt: Text) -> None:
        self.sio = sio
        self.bot_message_evt = bot_message_evt

    async def _send_message(self, socket_id: Text, response: Any) -> None:
        """Sends a message to the recipient using the bot event."""
        await self.sio.emit(self.bot_message_evt, response, room=socket_id)

    async def send_text_message(
        self, recipient_id: Text, text: Text, **kwargs: Any
    ) -> None:
        """Send a message through this channel."""
        for message_part in text.strip().split("\n\n"):
            await self._send_message(recipient_id, {"text": message_part})

    async def send_image_url(
        self, recipient_id: Text, image: Text, **kwargs: Any
    ) -> None:
        """Sends an image to the output"""

        message = {"attachment": {"type": "image", "payload": {"src": image}}}
        await self._send_message(recipient_id, message)

    async def send_text_with_buttons(
        self,
        recipient_id: Text,
        text: Text,
        buttons: List[Dict[Text, Any]],
        **kwargs: Any,
    ) -> None:
        """Sends buttons to the output."""

        # split text and create a message for each text fragment
        # the or makes sure there is at least one message we can attach the quick
        # replies to
        message_parts = text.strip().split("\n\n") or [text]
        messages = [{"text": message, "quick_replies": []} for message in message_parts]

        # attach all buttons to the last text fragment
        for button in buttons:
            messages[-1]["quick_replies"].append(
                {
                    "content_type": "text",
                    "title": button["title"],
                    "payload": button["payload"],
                }
            )

        for message in messages:
            await self._send_message(recipient_id, message)

    async def send_elements(
        self, recipient_id: Text, elements: Iterable[Dict[Text, Any]], **kwargs: Any
    ) -> None:
        """Sends elements to the output."""

        for element in elements:
            message = {
                "attachment": {
                    "type": "template",
                    "payload": {"template_type": "generic", "elements": element},
                }
            }

            await self._send_message(recipient_id, message)

    async def send_custom_json(
        self, recipient_id: Text, json_message: Dict[Text, Any], **kwargs: Any
    ) -> None:
        """Sends custom json to the output"""

        json_message.setdefault("room", recipient_id)

        await self.sio.emit(self.bot_message_evt, **json_message)

    async def send_attachment(
        self, recipient_id: Text, attachment: Dict[Text, Any], **kwargs: Any
    ) -> None:
        """Sends an attachment to the user."""
        await self._send_message(recipient_id, {"attachment": attachment})


class SocketIOInput(InputChannel):
    """A socket.io input channel."""

    @classmethod
    def name(cls) -> Text:
        return "socketio"

    @classmethod
    def from_credentials(cls, credentials: Optional[Dict[Text, Any]]) -> InputChannel:
        credentials = credentials or {}
        return cls(
            credentials.get("user_message_evt", "user_uttered"),
            credentials.get("bot_message_evt", "bot_uttered"),
            credentials.get("namespace"),
            credentials.get("session_persistence", False),
            credentials.get("socketio_path", "/socket.io"),
        )

    def __init__(
        self,
        user_message_evt: Text = "user_uttered",
        bot_message_evt: Text = "bot_uttered",
        namespace: Optional[Text] = None,
        session_persistence: bool = False,
        socketio_path: Optional[Text] = "/socket.io",
    ):
        self.bot_message_evt = bot_message_evt
        self.session_persistence = session_persistence
        self.user_message_evt = user_message_evt
        self.namespace = namespace
        self.socketio_path = socketio_path
        self.sio = None

    def get_output_channel(self) -> Optional["OutputChannel"]:
        if self.sio is None:
            rasa.shared.utils.io.raise_warning(
                "SocketIO output channel cannot be recreated. "
                "This is expected behavior when using multiple Sanic "
                "workers or multiple Rasa Open Source instances. "
                "Please use a different channel for external events in these "
                "scenarios."
            )
            return
        return SocketIOOutput(self.sio, self.bot_message_evt)

    def blueprint(
        self, on_new_message: Callable[[UserMessage], Awaitable[Any]]
    ) -> Blueprint:
        # Workaround so that socketio works with requests from other origins.
        # https://github.com/miguelgrinberg/python-socketio/issues/205#issuecomment-493769183
        sio = AsyncServer(async_mode="sanic", cors_allowed_origins=[])
        socketio_webhook = SocketBlueprint(
            sio, self.socketio_path, "socketio_webhook", __name__
        )

        # make sio object static to use in get_output_channel
        self.sio = sio

        @socketio_webhook.route("/", methods=["GET"])
        async def health(_: Request) -> HTTPResponse:
            return response.json({"status": "ok"})

        @sio.on("connect", namespace=self.namespace)
        async def connect(sid: Text, _) -> None:
            logger.debug(f"User {sid} connected to socketIO endpoint.")

        @sio.on("disconnect", namespace=self.namespace)
        async def disconnect(sid: Text) -> None:
            logger.debug(f"User {sid} disconnected from socketIO endpoint.")

        @sio.on("session_request", namespace=self.namespace)
        async def session_request(sid: Text, data: Optional[Dict]):
            if data is None:
                data = {}
            if "session_id" not in data or data["session_id"] is None:
                data["session_id"] = uuid.uuid4().hex
            if self.session_persistence:
                sio.enter_room(sid, data["session_id"])
            await sio.emit("session_confirm", data["session_id"], room=sid)
            logger.debug(f"User {sid} connected to socketIO endpoint.")

        # arriva un nuovo messaggio da parte dell'utente
        @sio.on(self.user_message_evt, namespace=self.namespace)
        async def handle_message(sid: Text, data: Dict) -> Any:
            # cerca il database (chatbot) corretto, cioe' quello a cui il cliente e' connesso
            redis_ip = "$redis_ip"
            redis_port = $redis_port
            redis_db = redis.Redis(host=redis_ip, port=redis_port, db=0, decode_responses=True)
            sender_id = data["session_id"]
            redis_n_db = 0
            if redis_db.get(str(sender_id)) is not None:
                redis_n_db = int(redis_db.get(str(sender_id)))
            
            # connessione al db redis corretto
            redis_db = redis.Redis(host=redis_ip, port=redis_port, db=redis_n_db, decode_responses=True)
            assistenza = redis_db.get("CLIENTE:" + str(sender_id))
            if assistenza is not None:
                assistenza = eval(assistenza)[0]

            message = data["message"]
            # dal secondo messaggio in poi, invia tutto a Redis e non a Rasa
            if assistenza == "ASSISTENZA":
                # scrittura del messaggio (e suo indice) su Redis
                message_number = int(eval(redis_db.get("CLIENTE:" + str(sender_id)))[1]) + 1
                redis_db.set("CLIENTE:" + str(sender_id) + ":" + str(message_number), str(message))
                redis_db.set("CLIENTE:" + str(sender_id), str(["ASSISTENZA", message_number]))
                # azzera il timer di attesa dell'operatore
                now_timestamp = time.time()
                redis_db.set("TIMESTAMP:" + str(sender_id), now_timestamp)
                # dal secondo messaggio dell'utente non si passa da Rasa ma si invia tutto su Redis
                return
            # se e' un messaggio normale o e' il primo messaggio diretto all'assistenza
            else:
                # aggiunge il primo messaggio a Redis e dopo questo if lo invia a Rasa cosi' l'operatore puo' rispondere
                if assistenza == "ASSISTENZA_FIRST":
                    message = data["message"]
                    message_number = int(eval(redis_db.get("CLIENTE:" + str(sender_id)))[1]) + 1
                    redis_db.set("CLIENTE:" + str(sender_id) + ":" + str(message_number), str(message))
                    redis_db.set("CLIENTE:" + str(sender_id), str(["ASSISTENZA", message_number]))
                output_channel = SocketIOOutput(sio, self.bot_message_evt)
                if self.session_persistence:
                    if not data.get("session_id"):
                        rasa.shared.utils.io.raise_warning(
                            "A message without a valid session_id "
                            "was received. This message will be "
                            "ignored. Make sure to set a proper "
                            "session id using the "
                            "session_request socketIO event."
                        )
                        return
                    sender_id = data["session_id"]
                else:
                    sender_id = sid
                    
                message = UserMessage(
                    data["message"], output_channel, sender_id, input_channel=self.name()
                )

                await on_new_message(message)
        return socketio_webhook
EOF

exit 0