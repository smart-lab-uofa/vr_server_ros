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

    def __del__(self):
        self.pool.close()
        self.pool.terminate()

    def sender(self):
        while True:
            data = self.send_queue.get()
            #self.get_logger().info("Sending mesh chunk")
            broadcast(
                self.clients[0],
                data
            )
            if self.send_queue.empty():
                self.chunks_pushed = True

    def update_chunks(self):
        self.new_chunks = True
        self.chunks_pushed = False

    def chunks_updated(self):
        return self.chunks_pushed

    @staticmethod
    def send_chunk(old_num, n, chunk):
        if n > old_num or chunk.has_been_updated:
            return MeshStreamer.serialize_chunk(n, chunk)
        return None


    def update(self, mapping_state):
        if mapping_state == sl.SPATIAL_MAPPING_STATE.OK:
            self.update_mesh()

    def update_mesh(self):
        if self.new_chunks:
            num_chunks = len(self.mesh.chunks)
            [self.send_queue.put(MeshStreamer.serialize_chunk(i, c)) for i, c in enumerate(self.mesh.chunks) if i > self.num_chunks or c.has_been_updated]

            self.num_chunks = num_chunks
            self.new_chunks = False

    @staticmethod
    def serialize_chunk(idx, chunk) -> bytes:
        vertices = chunk.vertices.ravel()
        triangles = chunk.triangles.ravel()
        normals = chunk.normals.ravel()
        buffer = bytes(0)

        buffer += struct.pack("HHHH", idx, len(vertices), len(triangles), 0)
        buffer += vertices.tobytes()
        buffer += triangles.tobytes()
        buffer += normals.tobytes()
        return buffer

    async def push_all_chunks(self, websocket):
        for i in range(min(self.num_chunks, len(self.mesh.chunks))):
            await websocket.send(MeshStreamer.serialize_chunk(i, self.mesh.chunks[i]))

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
