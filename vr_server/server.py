import rclpy
from rclpy.node import Node

from vr_msgs.msg import Status, IndexedMesh
from vr_msgs.srv import GetChunks
from geometry_msgs.msg import Pose, Point, Quaternion
from mesh_msgs.msg import MeshGeometry, MeshTriangleIndices

from std_srvs.srv import SetBool

import pyzed.sl as sl
import json
import time
import asyncio
from functools import partial
from websockets.server import serve
from .streamer import MeshStreamer


class VRServer(Node):
    def __init__(self):

        # Setting up topic publishers
        super().__init__('vrserver')
        self.tracking_pub_ = self.create_publisher(PoseStamped, '~/tracking', 10)
        self.echo_sub_ = self.create_subscriber(PoseStamped, '~/tracking_echo', self.echo)
        # self.mesh_pub_ = self.create_publisher(IndexedMesh, '~/mesh', 10)
        self.status_pub_ = self.create_publisher(Status, '~/status', 10)
        self.mapping_srv_ = self.create_service(SetBool, "~/mapping", self.mapping_callback)
        # self.mesh_srv_ = self.create_service(GetChunks, "~/chunks", self.chunks_callback)

        # Creating callback
        self.timer = self.create_timer(0.05, self.timer_callback)

        # Setting up camera
        init = sl.InitParameters()
        init.camera_resolution = sl.RESOLUTION.SVGA
        init.camera_fps = 60 
        init.depth_mode = sl.DEPTH_MODE.ULTRA
        init.coordinate_units = sl.UNIT.METER
        init.coordinate_system = sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP # OpenGL's coordinate system is right_handed
        init.depth_maximum_distance = 8.

        self.zed = sl.Camera()
        status = self.zed.open(init)

        camera_infos = self.zed.get_camera_information()
        pose = sl.Pose()

        tracking_state = sl.POSITIONAL_TRACKING_STATE.OFF
        positional_tracking_parameters = sl.PositionalTrackingParameters()
        positional_tracking_parameters.set_floor_as_origin = True
        returned_state = self.zed.enable_positional_tracking(positional_tracking_parameters)
        # 6144
        self.spatial_mapping_parameters = sl.SpatialMappingParameters(resolution = sl.MAPPING_RESOLUTION.MEDIUM,mapping_range =  sl.MAPPING_RANGE.MEDIUM,max_memory_usage = 4096,save_texture = False,use_chunk_only = True,reverse_vertex_order = False,map_type = sl.SPATIAL_MAP_TYPE.MESH)
        self.mesh = sl.Mesh()

        self.tracking_state = sl.POSITIONAL_TRACKING_STATE.OFF
        self.mapping_state = sl.SPATIAL_MAPPING_STATE.NOT_ENABLED


        self.runtime_parameters = sl.RuntimeParameters()
        self.runtime_parameters.confidence_threshold = 50

        stream_params = sl.StreamingParameters()
        stream_params.codec = sl.STREAMING_CODEC.H265
        self.zed.enable_streaming(stream_params)

        self.mapping_activated = False

        self.image = sl.Mat()
        self.pose = sl.Pose()

        self.last_call = time.time()

        # Setting up streaming
        self.num_chunks = 0

        self.get_logger().info("Finished setup")
        self.get_logger().info(str(self.mapping_state))

        self.streamer = MeshStreamer(self.mesh, self.get_logger)

    def timer_callback(self):
        # self.get_logger().info("Timer callback")
        if self.zed.grab(self.runtime_parameters) == sl.ERROR_CODE.SUCCESS:
            self.zed.retrieve_image(self.image, sl.VIEW.LEFT)
            self.tracking_state = self.zed.get_position(self.pose)

            if self.mapping_activated:
                self.mapping_state = self.zed.get_spatial_mapping_state()
                duration = time.time() - self.last_call
                if duration > .5:
                    self.zed.request_spatial_map_async()
                    self.last_call = time.time()
                if self.zed.get_spatial_map_request_status_async() == sl.ERROR_CODE.SUCCESS:
                    self.zed.retrieve_spatial_map_async(self.mesh)
                    self.streamer.update_chunks()
                    # print("Updated chunks")

            self.streamer.update(self.mapping_state)
            
            p = PoseStamped()
            p.header.stamp = self.get_clodk().now().to_msg()
            p.position = Point()
            translation = self.pose.get_translation().get()
            p.position.x = translation[0]
            p.position.y = translation[1]
            p.position.z = translation[2]
            p.orientation = Quaternion()
            orientation = self.pose.get_orientation().get()
            p.orientation.x = orientation[0]
            p.orientation.y = orientation[1]
            p.orientation.z = orientation[2]
            p.orientation.w = orientation[3]

            self.tracking_pub_.publish(p)

            s = Status()
            s.tracking_state = str(self.tracking_state)
            s.mapping_state = str(self.mapping_state)

            self.status_pub_.publish(s)
    

    def echo(self, msg: PoseStamped):
        latency = (self.get_clock().now() - msg.header.stamp)

        self.get_logger().info("Latency: " + str(latency))

      # def update_chunks(self):
    #     num_chunks = len(self.mesh.chunks)

    #     if num_chunks > self.num_chunks:
    #         for n in range(self.num_chunks, num_chunks):
    #             self.mesh_pub_.publish(self.make_mesh_msg(n, self.mesh.chunks[n]))

    #     for n in range(self.num_chunks):
    #         if n < num_chunks and self.mesh.chunks[n].has_been_updated:
    #             self.mesh_pub_.publish(self.make_mesh_msg(n, self.mesh.chunks[n]))

    #     self.num_chunks = num_chunks

    def make_mesh_msg(self, n, chunk):
        im = IndexedMesh()
        m = MeshGeometry()
        m.faces = []
        for t in chunk.triangles:
            tri = MeshTriangleIndices()
            tri.vertex_indices = t
            m.faces.append(tri)
        m.vertices = []
        for v in chunk.vertices:
            p = Point()
            p.x = float(v[0])
            p.y = float(v[1])
            p.z = float(v[2])
            m.vertices.append(p)
        m.vertex_normals = []
        for norm in chunk.normals:
            p = Point()
            p.x = float(norm[0])
            p.y = float(norm[1])
            p.z = float(norm[2])
            m.vertex_normals.append(p)
        im.mesh = m
        im.i = n
        return im
        # self.mesh_pub_.publish(im)

    def mapping_callback(self, request, response):
        if self.mapping_activated != request.data:
            if self.mapping_activated:
                # Extract and clean up whole mesh
                self.zed.extract_whole_spatial_map(self.mesh)

                filter_params = sl.MeshFilterParameters()
                filter_params.set(sl.MESH_FILTER.MEDIUM)

                self.mesh.filter(filter_params, True)

                # Apply textures to the mesh
                self.mesh.apply_texture(sl.MESH_TEXTURE_FORMAT.RGBA)

                self.mapping_state = sl.SPATIAL_MAPPING_STATE.NOT_ENABLED
                self.mapping_activated = False
                self.zed.disable_spatial_mapping()
            else:
                # Reset position
                init_pose = sl.Transform()
                self.zed.reset_positional_tracking(init_pose)

                # Reset spatial mapping
                self.zed.enable_spatial_mapping(self.spatial_mapping_parameters)
                self.mesh.clear()
                self.last_call = time.time()
                self.mapping_activated = True

        self.get_logger().info(str(self.mapping_state))
        response.success = True
        response.message = ""
        return response

    def chunks_callback(self, request, response):
        response.chunks = [self.make_mesh_msg(i, c) for i, c in enumerate(self.mesh.chunks)]
        self.get_logger().info(f"Responding to chunks request with {len(response.chunks)} chunks")
        return response


async def inner_main(args=None):
    rclpy.init(args=args)

    vr_server = VRServer()
    async with serve(vr_server.streamer.connect_handler, "0.0.0.0", 5555):
        while rclpy.ok():
            rclpy.spin_once(vr_server, timeout_sec=0)
            await asyncio.sleep(1e-4)

    # Destroy the node explicitly
    # (optional - otherwise it will be done automatically
    # when the garbage collector destroys the node object)
    vr_server.destroy_node()
    rclpy.shutdown()

def main(args=None):
    asyncio.run(inner_main())


if __name__ == '__main__':
    main()
