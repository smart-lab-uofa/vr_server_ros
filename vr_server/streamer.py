import asyncio
from websockets.server import serve
from websockets import broadcast
import json
import pyzed.sl as sl
import numpy as np
import time
import struct


class MeshStreamer:
    def __init__(self, mesh):
        self.clients = set()
        self.mesh = mesh
        self.new_chunks = False
        self.chunks_pushed = True
        self.num_chunks = 0
        self.start = time.time()
        self.started = False
        self.available = False
        self.should_change_state = False
        self.current_mapping_state = sl.SPATIAL_MAPPING_STATE.NOT_ENABLED

    def update_chunks(self):
        self.new_chunks = True
        self.chunks_pushed = False

    def chunks_updated(self):
        return self.chunks_pushed

    def update(self, mapping_state):
        if mapping_state == sl.SPATIAL_MAPPING_STATE.OK:
            self.update_mesh()

    def update_mesh(self):
        if self.new_chunks:
            num_chunks = len(self.mesh.chunks)
            # print(num_chunks)

            # pushing new chunks
            if num_chunks > self.num_chunks:
                for n in range(self.num_chunks, num_chunks):
                    broadcast(
                        self.clients,
                        self.serialize_chunk(n, num_chunks, self.mesh.chunks[n]),
                    )

            # updating existing chunks
            # print("updating existing chunks")
            for n in range(self.num_chunks):
                if n < num_chunks and self.mesh.chunks[n].has_been_updated:
                    # if self.mesh.chunks[n].triangles and self.mesh.chunks[n].vertices:
                    broadcast(
                        self.clients,
                        self.serialize_chunk(n, num_chunks, self.mesh.chunks[n]),
                    )

            self.num_chunks = num_chunks
            self.new_chunks = False
            self.chunks_pushed = True

    def serialize_chunk(self, idx, size, chunk) -> bytes:
        vertices = chunk.vertices.flatten()
        triangles = chunk.triangles.flatten()
        normals = chunk.normals.flatten()
        buffer = bytes()

        buffer += struct.pack("HHHH", idx, len(vertices), len(triangles), 0)
        buffer += vertices.tobytes()
        buffer += triangles.tobytes()
        buffer += normals.tobytes()
        return buffer

    async def push_all_chunks(self, websocket):
        for i in range(min(self.num_chunks, len(self.mesh.chunks))):
            await websocket.send(self.serialize_chunk(i, self.num_chunks, self.mesh.chunks[i]))

    async def connect_handler(self, websocket):
        self.clients.add(websocket)
        await self.push_all_chunks(websocket)
        await websocket.wait_closed()
        self.clients.remove(websocket)

        if len(self.clients) == 0:
            self.available = False


async def main():
    s = Streamer("mesh")
    async with serve(s.connect_handler, "10.42.0.1", 5555):
        while True:
            # print("Latency:", s.latency)
            s.update(
                np.array(
                    [
                        [0.0, 1.0, 2.0, 3.0],
                        [4.0, 5.0, 6.0, 7.0],
                        [8.0, 9.0, 0.0, 1.0],
                        [2.0, 3.0, 4.0, 5.0],
                    ]
                ),
                0,
                0,
            )
            await asyncio.sleep(0.1)


if __name__ == "__main__":
    asyncio.run(main())
