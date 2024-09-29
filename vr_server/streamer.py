import asyncio
import os
from websockets.server import serve
from websockets import broadcast
import json
import pyzed.sl as sl
import numpy as np
import time
import struct
import ffmpeg
import threading
import queue


class MeshStreamer:
    def __init__(self, mesh, get_logger):
        self.clients = (set(), set())
        self.mesh = mesh
        self.get_logger = get_logger
        self.new_chunks = False
        self.chunks_pushed = True
        self.num_chunks = 0
        self.start = time.time()
        self.started = False
        self.available = False
        self.should_change_state = False
        self.current_mapping_state = sl.SPATIAL_MAPPING_STATE.NOT_ENABLED
        self.send_queue = queue.Queue()
        self.sender = threading.Thread(target=self.sender)
        self.sender.start()

    def sender(self):
        while True:
            n, num_chunks, chunk = self.send_queue.get()
            broadcast(
                self.clients[0],
                self.serialize_chunk(n, num_chunks, chunk),
            )
            if self.send_queue.empty():
                self.chunks_pushed = True

    def update_chunks(self):
        self.new_chunks = True
        self.chunks_pushed = False

    def chunks_updated(self):
        return self.chunks_pushed

    def update(self, mapping_state):
        self.get_logger().info(str(mapping_state))
        if mapping_state == sl.SPATIAL_MAPPING_STATE.OK:
            self.update_mesh()

    def update_mesh(self):
        if self.new_chunks:
            num_chunks = len(self.mesh.chunks)
            # print(num_chunks)

            # pushing new chunks
            if num_chunks > self.num_chunks:
                for n in range(self.num_chunks, num_chunks):
                    self.send_queue.put((n, num_chunks, self.mesh.chunks[n]))

            # updating existing chunks
            # print("updating existing chunks")
            for n in range(self.num_chunks):
                if n < num_chunks and self.mesh.chunks[n].has_been_updated:
                    # if self.mesh.chunks[n].triangles and self.mesh.chunks[n].vertices:
                    self.send_queue.put((n, num_chunks, self.mesh.chunks[n]))

            self.num_chunks = num_chunks
            self.new_chunks = False

    def serialize_chunk(self, idx, size, chunk) -> bytes:
        vertices = chunk.vertices.flatten()
        triangles = chunk.triangles.flatten()
        normals = chunk.normals.flatten()
        buffer = bytes(0)

        buffer += struct.pack("HHHH", idx, len(vertices), len(triangles), 0)
        buffer += vertices.tobytes()
        buffer += triangles.tobytes()
        buffer += normals.tobytes()
        return buffer

    async def push_all_chunks(self, websocket):
        for i in range(min(self.num_chunks, len(self.mesh.chunks))):
            await websocket.send(self.serialize_chunk(i, self.num_chunks, self.mesh.chunks[i]))

    async def connect_handler(self, websocket):
        if websocket.path == "/mesh":
            self.clients[0].add(websocket)
            await self.push_all_chunks(websocket)
            await websocket.wait_closed()
            self.clients[0].remove(websocket)
        elif websocket.path == "/stream":
            self.clients[1].add(websocket)
            await websocket.wait_closed()
            self.clients[1].remove(websocket)

        if len(self.clients[0]) == 0 and len(self.clients[1]) == 0:
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
