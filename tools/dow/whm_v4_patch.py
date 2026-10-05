#!/usr/bin/env python3
"""Compatibility shims: parse Dawn of War *Definitive Edition* WHM (RSGM v4)
with relic-tool-chunky's v3 WHM reader.

Definitive changes observed so far:
  - RSGM folder chunk version 4 (v3 layout still matches at folder level)
  - new folder chunk types (STXT = texture list) unknown to the converter
  - MSLC data chunk: reserved header fields non-zero, new vertex-size ids
"""
import io
import sys

from relic.chunky.serializer import read_chunky
from relic.chunky_formats.dow.whm import whm as W
from relic.chunky_formats.dow.whm import mesh as M
import relic.chunky_formats.convertable as cv


def patch():
    # RSGM v4 uses the v3 folder layout
    W.RsgmChunkFactory.VERSIONS.append(4)
    getattr(W.RsgmChunkFactory, "_RsgmChunkFactory__MAP").update(
        {4: W.RsgmChunkV3})
    W.RsgmChunkV3._VERSION = 4

    # tolerate unknown chunk types (STXT etc.) instead of KeyError
    orig_convert_many = cv.ChunkConverterFactory.convert_many

    def tolerant(self, chunks):
        out = []
        for c in chunks:
            try:
                out.append(self.convert(c))
            except KeyError as e:
                print("skip unknown chunk:", e)
        return out

    cv.ChunkConverterFactory.convert_many = tolerant

    # MSLC v4: same body layout as v3 except reserved header field rsv0_a may
    # be non-zero (2 observed). Replicate the v3 parser without that assert.
    orig_mslc_data = M.MslcDataChunk.convert.__func__

    def mslc_data_convert(cls, chunk):
        try:
            return orig_mslc_data(cls, chunk)
        except AssertionError:
            raw = chunk.raw_bytes
            with io.BytesIO(raw) as stream:
                rsv0_a, flag, val, rsv0_b = \
                    M.MslcDataChunk.HEADER_LAYOUT.unpack_stream(stream)
                bone_count = M.MslcDataChunk.COUNT_LAYOUT.unpack_stream(stream)[0]
                bones = [M.MslcBoneInfo.unpack(stream)
                         for _ in range(bone_count)]
                vcount = M.MslcDataChunk.COUNT_LAYOUT.unpack_stream(stream)[0]
                vsid = M.MslcDataChunk.COUNT_LAYOUT.unpack_stream(stream)[0]
                v_size = {37: 32, 39: 48}[vsid]  # inline from v3 convert body
                vertex_data = M.MslcVertexData.unpack(stream, vcount, v_size)
                e = stream.read(4)
                assert e == b"\x00\x00\x00\x00", e
                index_buffer_count = \
                    M.MslcDataChunk.COUNT_LAYOUT.unpack_stream(stream)[0]
                index_buffers = [M.MslcSubmeshData.unpack(stream)
                                 for _ in range(index_buffer_count)]
                aaa = M.MslcDataChunk.COUNT_LAYOUT.unpack_stream(stream)[0]
                aaa_data = [stream.read(12) for _ in range(aaa)]
                aab = M.MslcDataChunk.COUNT_LAYOUT.unpack_stream(stream)[0]
                aab_data = [stream.read(24) for _ in range(aab)]
                aac = M.MslcDataChunk.COUNT_LAYOUT.unpack_stream(stream)[0]
                aac_data = [stream.read(40) for _ in range(aac)]
            return M.MslcDataChunk(chunk.header, (flag, val), (vsid,), bones,
                                   vertex_data, index_buffers, aaa_data,
                                   aab_data, aac_data)

    M.MslcDataChunk.convert = classmethod(mslc_data_convert)

    # MSLC v4 folder has extra child chunks (new Definitive sub-chunk);
    # relax the "exactly 2 children" assert
    orig_mslc_folder = M.MslcChunk.convert.__func__

    def mslc_folder_convert(cls, chunk):
        try:
            return orig_mslc_folder(cls, chunk)
        except AssertionError:
            converted = M.MslcChunkConverter.convert_many(chunk.chunks)
            coll = cv.ChunkCollectionX.list2col(converted)
            data = coll.find(M.MslcDataChunk)
            bvol = coll.find(M.BvolChunk)
            return M.MslcChunk(chunk.header, data, bvol)

    M.MslcChunk.convert = classmethod(mslc_folder_convert)

    # RSGM v4 adds STXT folders the v3 counter does not know; relax the
    # child-count assert by counting every consumed child
    orig_rsgm_v3 = W.RsgmChunkV3.convert.__func__

    def rsgm_v3_convert(cls, chunk):
        try:
            return orig_rsgm_v3(cls, chunk)
        except AssertionError:
            from relic.chunky_formats.dow.whm.whm import (
                TxtrChunk, ShdrChunk, SshrChunk, MsgrChunk, SkelChunk,
                MarkChunk, CamsChunk, RsgmChunkV3)
            from relic.chunky_formats.util import ChunkCollectionX
            converted = W.WhmChunkConverter.convert_many(chunk.chunks)
            col = ChunkCollectionX.list2col(converted)
            anim = col.find(W.AnimChunk)
            txtr = col.find(TxtrChunk, True)
            shdr = col.find(ShdrChunk, True)
            sshr = col.find(SshrChunk, True)
            msgr = col.find(MsgrChunk)
            skel = col.find(SkelChunk)
            mark = col.find(MarkChunk)
            cams = col.find(CamsChunk)
            return RsgmChunkV3(chunk.header, anim, txtr, shdr, sshr, msgr,
                                skel, mark, cams)

    W.RsgmChunkV3.convert = classmethod(rsgm_v3_convert)

    # top-level WHM v4 has extra chunks (STXT folders); relax "== 2"
    orig_whm_convert = W.WhmChunky.convert.__func__

    def whm_convert(cls, chunky):
        try:
            return orig_whm_convert(cls, chunky)
        except AssertionError:
            converted = W.WhmChunkConverter.convert_many(chunky.chunks)
            from relic.chunky_formats.util import ChunkCollectionX
            x = ChunkCollectionX.list2col(converted)
            fbif = x.find(W.FbifChunk)
            rsgm = x.find(W.RsgmChunk)
            return W.WhmChunky(chunky.header, fbif, rsgm)

    W.WhmChunky.convert = classmethod(whm_convert)


def main():
    patch()
    path = sys.argv[1]
    f = open(path, "rb")
    generic = read_chunky(f)
    whm = W.WhmChunky.convert(generic)
    r = whm.rsgm
    print("WHM OK; rsgm:", type(r).__name__, "| skel:", bool(r.skel))
    return 0


if __name__ == "__main__":
    sys.exit(main())
