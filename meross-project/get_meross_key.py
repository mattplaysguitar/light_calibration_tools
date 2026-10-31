import asyncio
import getpass
from meross_iot.http_api import MerossHttpClient

async def main():
    email = input("Meross email: ")
    password = getpass.getpass("Meross password: ")

    client = await MerossHttpClient.async_from_user_password(
        api_base_url="https://iotx-us.meross.com",
        email=email,
        password=password,
    )

    creds = client.cloud_credentials

    print("\nMeross key:")
    print(creds.key)

    print("\nUser ID:")
    print(creds.user_id)

    print("\nCloud domain:")
    print(creds.domain)

    await client.async_logout()

asyncio.run(main())