import os
import aiohttp

from aiohttp import BasicAuth
from typing import Type
from pydantic import BaseModel, Field
import vonage

from vocode.streaming.action.phone_call_action import TwilioPhoneCallAction, VonagePhoneCallAction
from vocode.streaming.models.actions import (
    ActionConfig,
    ActionInput,
    ActionOutput,
    ActionType,
)


class TransferCallActionConfig(ActionConfig, type=ActionType.TRANSFER_CALL):
    to_phone: str


class TransferCallVonageActionConfig(ActionConfig, type=ActionType.TRANSFER_CALL):
    to_phone: str

class TransferCallParameters(BaseModel):
    pass


class TransferCallResponse(BaseModel):
    status: str = Field("success", description="status of the transfer")


class TransferCallVonage(
    VonagePhoneCallAction[
        TransferCallActionConfig, TransferCallParameters, TransferCallResponse
    ]
):
    description: str = "transfers the call. use when you need to connect the active call to another phone line."
    parameters_type: Type[TransferCallParameters] = TransferCallParameters
    response_type: Type[TransferCallResponse] = TransferCallResponse

    def transfer_call(self, vonage_uuid, to_phone):
        client = vonage.Client(
            application_id=os.getenv("VONAGE_APPLICATION_ID"),
            private_key=os.getenv("VONAGE_PRIVATE_KEY"),
            secret=os.getenv("VONAGE_API_SECRET"),
            key=os.getenv("VONAGE_API_KEY")
        )

        ncco = [
            {
                "action": "connect",
                "endpoint": [
                    {
                        "type": "phone",
                        "number": to_phone
                    }
                ]
            }
        ]

        response = client.voice.update_call(
            vonage_uuid,
            {
                "action": "transfer",
                "destination": {
                    "type": "ncco",
                    "ncco": ncco
                }
            }
        )
        return response

    async def run(
        self, action_input: ActionInput[TransferCallParameters]
    ) -> ActionOutput[TransferCallResponse]:
        vonage_uuid = self.get_vonage_uuid(action_input)

        self.transfer_call(vonage_uuid, self.action_config.to_phone)

        return ActionOutput(
            action_type=action_input.action_config.type,
            response=TransferCallResponse(status="success"),
        )


class TransferCall(
    TwilioPhoneCallAction[
        TransferCallActionConfig, TransferCallParameters, TransferCallResponse
    ]
):
    description: str = "transfers the call. use when you need to connect the active call to another phone line."
    parameters_type: Type[TransferCallParameters] = TransferCallParameters
    response_type: Type[TransferCallResponse] = TransferCallResponse

    async def transfer_call(self, twilio_call_sid, to_phone):
        twilio_account_sid = os.environ["TWILIO_ACCOUNT_SID"]
        twilio_auth_token = os.environ["TWILIO_AUTH_TOKEN"]

        url = "https://api.twilio.com/2010-04-01/Accounts/{twilio_account_sid}/Calls/{twilio_auth_token}.json".format(
            twilio_account_sid=twilio_account_sid, twilio_auth_token=twilio_call_sid
        )

        twiml_data = "<Response><Dial>{to_phone}</Dial></Response>".format(
            to_phone=to_phone
        )

        payload = {"Twiml": twiml_data}

        auth = BasicAuth(twilio_account_sid, twilio_auth_token)

        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.post(url, data=payload) as response:
                if response.status != 200:
                    print(await response.text())
                    raise Exception("failed to update call")
                else:
                    return await response.json()

    async def run(
        self, action_input: ActionInput[TransferCallParameters]
    ) -> ActionOutput[TransferCallResponse]:
        twilio_call_sid = self.get_twilio_sid(action_input)

        await self.transfer_call(twilio_call_sid, self.action_config.to_phone)

        return ActionOutput(
            action_type=action_input.action_config.type,
            response=TransferCallResponse(status="success"),
        )
