import asyncio
import nats

async def main():
    nc = await nats.connect("nats://nats:4222")
    await nc.publish("council.broadcast", b"hello-e2e")
    await nc.close()

asyncio.run(main())
