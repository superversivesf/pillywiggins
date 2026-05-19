import asyncio
import sys
import nats

msgs = []

async def handler(msg):
    msgs.append(msg.data.decode())

async def main():
    nc = await nats.connect("nats://nats:4222")
    sub = await nc.subscribe("council.broadcast", cb=handler)
    for _ in range(30):
        await asyncio.sleep(0.5)
        if any("hello-e2e" in m for m in msgs):
            break
    await sub.unsubscribe()
    await nc.close()
    if not any("hello-e2e" in m for m in msgs):
        print("FAIL: no message received", file=sys.stderr)
        sys.exit(1)
    print("PASS: received message")

asyncio.run(main())
