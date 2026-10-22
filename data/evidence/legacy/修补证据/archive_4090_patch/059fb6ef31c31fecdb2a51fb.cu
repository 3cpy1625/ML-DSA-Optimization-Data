// Standalone operator audit. Production headers and scalar comparator are sealed inputs.
// This does not load or modify the nine production ML-DSA modules.
#include <cuda_runtime.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include "params.h"
#include "fips202/fips202.cuh"
#include "loce/pqc/primitives/cuda/scalar_keccak_split32_named.cuh"

#define CUDA_OK(x) do { const auto e=(x); if(e!=cudaSuccess) throw std::runtime_error(std::string(#x)+": "+cudaGetErrorString(e)); } while(0)
__device__ const uint64_t keccak_f_round_constants[24]={0x1ULL,0x8082ULL,0x800000000000808aULL,0x8000000080008000ULL,0x808bULL,0x80000001ULL,0x8000000080008081ULL,0x8000000000008009ULL,0x8aULL,0x88ULL,0x80008009ULL,0x8000000aULL,0x8000808bULL,0x800000000000008bULL,0x8000000000008089ULL,0x8000000000008003ULL,0x8000000000008002ULL,0x8000000000000080ULL,0x800aULL,0x800000008000000aULL,0x8000000080008081ULL,0x8000000000008080ULL,0x80000001ULL,0x8000000080008008ULL};
__constant__ uint64_t keccak_f_round_constants_PTX[24];
__constant__ int8_t offset_constants_PTX[32];
__constant__ uint64_t keccak_lane_params_PTX[32];
__constant__ uint32_t keccak_lane_params_u32_PTX[32];

__device__ __forceinline__ uint64_t rol64(uint64_t x, unsigned n) {
    return n == 0 ? x : (x << n) | (x >> (64 - n));
}

__device__ __forceinline__ void scalar_keccak_f1600(uint64_t s[25]) {
    constexpr unsigned rho[25] = {
        0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43,
        25, 39, 41, 45, 15, 21, 8, 18, 2, 61, 56, 14};
    uint64_t b[25];
    uint64_t c[5];

#pragma unroll
    for (unsigned round = 0; round < 24; ++round) {
#pragma unroll
        for (unsigned x = 0; x < 5; ++x)
            c[x] = s[x] ^ s[x + 5] ^ s[x + 10] ^ s[x + 15] ^ s[x + 20];
#pragma unroll
        for (unsigned y = 0; y < 5; ++y) {
#pragma unroll
            for (unsigned x = 0; x < 5; ++x)
                s[x + 5 * y] ^= c[(x + 4) % 5] ^ rol64(c[(x + 1) % 5], 1);
        }
#pragma unroll
        for (unsigned y = 0; y < 5; ++y) {
#pragma unroll
            for (unsigned x = 0; x < 5; ++x) {
                const unsigned dy = (2 * x + 3 * y) % 5;
                b[y + 5 * dy] = rol64(s[x + 5 * y], rho[x + 5 * y]);
            }
        }
#pragma unroll
        for (unsigned y = 0; y < 5; ++y) {
#pragma unroll
            for (unsigned x = 0; x < 5; ++x)
                s[x + 5 * y] = b[x + 5 * y] ^
                    ((~b[(x + 1) % 5 + 5 * y]) & b[(x + 2) % 5 + 5 * y]);
        }
        s[0] ^= keccak_f_round_constants_PTX[round];
    }
}

struct Trace { uint32_t blocks, accepted, candidates, checksum, status; };
static_assert(sizeof(Trace)==20,"trace ABI");
struct Work { uint32_t logical_squeeze,absorb,executed_squeeze,drain_dummy; };
struct WarpWork { uint32_t valid_pairs,padded_pairs,absorb_rounds,squeeze_rounds; };
static_assert(sizeof(Work)==16 && sizeof(WarpWork)==16,"work ABI");

template<int Warp> struct Stream;
template<> struct Stream<0> {
    uint64_t s[25]; int rate;
    __device__ Stream() : s{}, rate(0) {}
    __device__ void init(const uint8_t* in,int len,int r) {
        rate=r;
        while(len>=rate) {
            for(int i=0;i<rate;++i) s[i/8]^=uint64_t(in[i])<<(8*(i%8));
            scalar_keccak_f1600(s); in+=rate; len-=rate;
        }
        for(int i=0;i<len;++i) s[i/8]^=uint64_t(in[i])<<(8*(i%8));
        s[len/8]^=uint64_t(0x1f)<<(8*(len%8)); s[rate/8-1]^=UINT64_C(0x8000000000000000);
    }
    __device__ void next(uint8_t* out) {
        scalar_keccak_f1600(s);
        for(int i=0;i<rate;++i) out[i]=uint8_t(s[i/8]>>(8*(i%8)));
    }
};
template<> struct Stream<1> {
    uint64_t s; int rate;
    __device__ Stream() : s(0), rate(0) {}
    __device__ void init(const uint8_t* in,int len,int r) {
        rate=r; const int lane=threadIdx.x;
        while(len>=rate) {
            if(lane<rate/8) { uint64_t v=0; for(int j=0;j<8;++j) v|=uint64_t(in[lane*8+j])<<(8*j); s^=v; }
            s=state_permute_PTX(s); in+=rate; len-=rate;
        }
        uint64_t v=0;
        for(int j=0;j<8;++j) if(lane*8+j<len) v|=uint64_t(in[lane*8+j])<<(8*j);
        s^=v;
        if(lane==len/8) s^=uint64_t(0x1f)<<(8*(len%8));
        if(lane==rate/8-1) s^=UINT64_C(0x8000000000000000);
    }
    __device__ void next(uint8_t* out) {
        __syncwarp(0xffffffffu); // Finish prior consumers before reusing the shared byte stream.
        s=state_permute_PTX(s);
        if(threadIdx.x<rate/8) for(int j=0;j<8;++j) out[threadIdx.x*8+j]=uint8_t(s>>(8*j));
        __syncwarp();
    }
};

__device__ void put_i32(uint8_t* out,int i,int32_t v) { reinterpret_cast<int32_t*>(out)[i]=v; }
__device__ int get_i32(const uint8_t* out,int i) { return reinterpret_cast<const int32_t*>(out)[i]; }

// op: 0 raw permutation, 1 SHAKE, 2 RejNTTPoly, 3 RejBoundedPoly,
// 4 ExpandMask polynomial decoding, 5 SampleInBall.
// The sampling parser is deliberately the same logical-lane-zero parser for all
// three backends: this isolates the Keccak state mapping, not ballot-compaction speed.
template<int Warp> __global__ void audit_kernel(
    const uint8_t* input,uint8_t* output,Trace* traces,Work* work,int n,int op,int rate,
    int input_bytes,int output_bytes,int units,int force_blocks,int budget,int stop) {
    const int lane=Warp?int(threadIdx.x):0;
    const int local=Warp?int(threadIdx.y):int(threadIdx.x);
    const int req=Warp?int(blockIdx.x*blockDim.y+threadIdx.y):int(blockIdx.x*blockDim.x+threadIdx.x);
    if(req>=n) return;
    extern __shared__ uint8_t shared[];
    uint8_t* buf=shared+local*168;
    const uint8_t* in=input+size_t(req)*input_bytes;
    uint8_t* out=output+size_t(req)*output_bytes;
    if(lane==0) for(int i=0;i<output_bytes;++i) out[i]=0;
    if(Warp) __syncwarp();
    if(op==0) {
        uint64_t s=0;
        if(Warp) {
            if(lane<25) for(int j=0;j<8;++j) s|=uint64_t(in[lane*8+j])<<(8*j);
            for(int i=0;i<budget;++i) s=state_permute_PTX(s);
            if(lane<25) for(int j=0;j<8;++j) out[lane*8+j]=uint8_t(s>>(8*j));
        } else {
            uint64_t state[25]{};
            for(int i=0;i<200;++i) state[i/8]|=uint64_t(in[i])<<(8*(i%8));
            for(int i=0;i<budget;++i) scalar_keccak_f1600(state);
            for(int i=0;i<200;++i) out[i]=uint8_t(state[i/8]>>(8*(i%8)));
        }
        if(Warp) __syncwarp();
        if(lane==0) { traces[req]={uint32_t(budget),200,0,0,0}; work[req]={uint32_t(budget),0,uint32_t(budget),0}; }
        return;
    }
    Stream<Warp> stream; stream.init(in,input_bytes,rate);
    uint32_t accepted=0,candidates=0,checksum=0,blocks=0;
    uint64_t reservoir=0,signs=0; int bits=0;
    const int width=GAMMA1==(1<<17)?18:20;
    for(int b=0;b<budget;++b) {
        stream.next(buf);
        if(lane==0) {
            ++blocks;
            uint32_t head=uint32_t(buf[0])|(uint32_t(buf[1])<<8)|(uint32_t(buf[2])<<16)|(uint32_t(buf[3])<<24);
            checksum=((checksum<<5)|(checksum>>27)) ^ head ^ (uint32_t(b+1)*UINT32_C(0x9e3779b9));
            if(op==1) {
                for(int j=0;j<rate;++j) {
                    ++candidates;
                    if(accepted<uint32_t(units)) out[accepted++]=buf[j];
                    if(stop && accepted==uint32_t(units)) break;
                }
            } else if(op==2) {
                for(int j=0;j+2<rate;j+=3) {
                    uint32_t v=b<force_blocks?UINT32_C(0x7fffff):
                        ((uint32_t(buf[j])|(uint32_t(buf[j+1])<<8)|(uint32_t(buf[j+2])<<16))&UINT32_C(0x7fffff));
                    ++candidates;
                    if(v<DILITHIUM_Q && accepted<256) put_i32(out,accepted++,int32_t(v));
                    if(stop && accepted==256) break;
                }
            } else if(op==3) {
                for(int j=0;j<2*rate;++j) {
                    int v=b<force_blocks?15:int((buf[j/2]>>(4*(j%2)))&15); ++candidates;
                    if(ETA==2) { if(v<15 && accepted<256) { v-=((205*v)>>10)*5; put_i32(out,accepted++,2-v); } }
                    else { if(v<9 && accepted<256) put_i32(out,accepted++,4-v); }
                    if(stop && accepted==256) break;
                }
            } else if(op==4) {
                for(int j=0;j<rate;++j) {
                    ++candidates;
                    if(accepted<256) {
                        reservoir|=uint64_t(buf[j])<<bits; bits+=8;
                        while(bits>=width && accepted<256) {
                            int v=int(reservoir&((UINT64_C(1)<<width)-1));
                            put_i32(out,accepted++,GAMMA1-v); reservoir>>=width; bits-=width;
                        }
                    }
                    if(stop && accepted==256) break;
                }
            } else if(op==5) {
                int start=0;
                if(b==0) { for(int j=0;j<8;++j) signs|=uint64_t(buf[j])<<(8*j); start=8; }
                for(int j=start;j<rate;++j) {
                    int v=b<force_blocks?255:int(buf[j]); ++candidates;
                    if(accepted<uint32_t(TAU)) {
                        int i=256-TAU+int(accepted);
                        if(v<=i) { put_i32(out,i,get_i32(out,v)); put_i32(out,v,1-2*int(signs&1)); signs>>=1; ++accepted; }
                    }
                    if(stop && accepted==uint32_t(TAU)) break;
                }
            }
        }
        uint32_t a=accepted;
        if(Warp) a=__shfl_sync(0xffffffff,a,0);
        if(stop && a==uint32_t(units)) break;
    }
    if(lane==0) { traces[req]={blocks,accepted,candidates,checksum,accepted==uint32_t(units)?0u:1u}; work[req]={blocks,uint32_t(input_bytes/rate),blocks,0}; }
}

// Harness-only byte stream. The permutation is the verbatim sealed production header.
template<> struct Stream<2> {
    uint32_t s[25]; int rate; unsigned half;
    __device__ Stream() : s{}, rate(0), half(threadIdx.x & 1u) {}
    __device__ void init(const uint8_t* in,int len,int r,bool valid) {
        rate=r;
        while(len>=rate) {
            for(int i=0;i<rate;++i)
                if(valid && unsigned((i%8)/4)==half) s[i/8]^=uint32_t(in[i])<<(8*(i%4));
            mlkem_keccak_split32_named_permute<1,false>(s,half);
            if(valid) in+=rate;
            len-=rate;
        }
        for(int i=0;i<len;++i)
            if(valid && unsigned((i%8)/4)==half) s[i/8]^=uint32_t(in[i])<<(8*(i%4));
        if(unsigned((len%8)/4)==half) s[len/8]^=uint32_t(0x1f)<<(8*(len%4));
        if(half==1) s[rate/8-1]^=UINT32_C(0x80000000);
    }
    __device__ void next(uint8_t* out) {
        __syncwarp(0xffffffffu); // Live draining warps collectively finish prior byte consumers.
        mlkem_keccak_split32_named_permute<1,false>(s,half);
        for(int word=0;word<rate/8;++word)
            for(int j=0;j<4;++j) out[word*8+half*4+j]=uint8_t(s[word]>>(8*j));
        __syncwarp(0xffffffffu);
    }
};

// 128 physical threads / CTA, 64 logical states; no live pair leaves a draining warp.
// Work and WarpWork are separate from the existing logical Trace ABI.
__global__ void audit_split32_kernel(
    const uint8_t* input,uint8_t* output,Trace* traces,Work* work,WarpWork* warp_work,
    int n,int op,int rate,int input_bytes,int output_bytes,int units,
    int force_blocks,int budget,int stop) {
    const unsigned lane=threadIdx.x&31u, half=lane&1u;
    const int local=int(threadIdx.x>>1), req=int(blockIdx.x*64+local);
    const int warp_index=int(blockIdx.x*4+(threadIdx.x>>5));
    const bool valid=req<n;
    const unsigned valid_lanes=__ballot_sync(0xffffffffu,valid);
    const unsigned valid_pairs=unsigned(__popc(valid_lanes))/2u;
    if(valid_pairs==0) { // Warp-uniform exit; no lane from a live warp exits here.
        if(lane==0) warp_work[warp_index]={0,16,0,0};
        return;
    }
    extern __shared__ uint8_t shared[];
    uint8_t* buf=shared+local*168;
    const uint8_t* in=valid?input+size_t(req)*input_bytes:nullptr;
    uint8_t* out=valid?output+size_t(req)*output_bytes:nullptr;
    if(half==0 && valid) for(int i=0;i<output_bytes;++i) out[i]=0;
    __syncwarp(0xffffffffu);
    if(op==0) {
        uint32_t state[25]{};
        if(valid) for(int word=0;word<25;++word)
            for(int j=0;j<4;++j) state[word]|=uint32_t(in[word*8+half*4+j])<<(8*j);
        for(int i=0;i<budget;++i) mlkem_keccak_split32_named_permute<1,false>(state,half);
        if(valid) for(int word=0;word<25;++word)
            for(int j=0;j<4;++j) out[word*8+half*4+j]=uint8_t(state[word]>>(8*j));
        __syncwarp(0xffffffffu);
        if(half==0 && valid) {
            traces[req]={uint32_t(budget),200,0,0,0};
            work[req]={uint32_t(budget),0,uint32_t(budget),0};
        }
        if(lane==0) warp_work[warp_index]={valid_pairs,16-valid_pairs,0,uint32_t(budget)};
        return;
    }
    Stream<2> stream; stream.init(in,input_bytes,rate,valid);
    uint32_t accepted=0,candidates=0,checksum=0,blocks=0,executed=0;
    uint64_t reservoir=0,signs=0; int bits=0;
    const int width=GAMMA1==(1<<17)?18:20;
    for(int b=0;b<budget;++b) {
        stream.next(buf); ++executed;
        // Completed real pairs keep doing dummy permutations but freeze logical state.
        if(half==0 && valid && (!stop || accepted<uint32_t(units))) {
            ++blocks;
            uint32_t head=uint32_t(buf[0])|(uint32_t(buf[1])<<8)|(uint32_t(buf[2])<<16)|(uint32_t(buf[3])<<24);
            checksum=((checksum<<5)|(checksum>>27)) ^ head ^ (uint32_t(b+1)*UINT32_C(0x9e3779b9));
            if(op==1) {
                for(int j=0;j<rate;++j) {
                    ++candidates;
                    if(accepted<uint32_t(units)) out[accepted++]=buf[j];
                    if(stop && accepted==uint32_t(units)) break;
                }
            } else if(op==2) {
                for(int j=0;j+2<rate;j+=3) {
                    uint32_t v=b<force_blocks?UINT32_C(0x7fffff):
                        ((uint32_t(buf[j])|(uint32_t(buf[j+1])<<8)|(uint32_t(buf[j+2])<<16))&UINT32_C(0x7fffff));
                    ++candidates;
                    if(v<DILITHIUM_Q && accepted<256) put_i32(out,accepted++,int32_t(v));
                    if(stop && accepted==256) break;
                }
            } else if(op==3) {
                for(int j=0;j<2*rate;++j) {
                    int v=b<force_blocks?15:int((buf[j/2]>>(4*(j%2)))&15); ++candidates;
                    if(ETA==2) { if(v<15 && accepted<256) { v-=((205*v)>>10)*5; put_i32(out,accepted++,2-v); } }
                    else { if(v<9 && accepted<256) put_i32(out,accepted++,4-v); }
                    if(stop && accepted==256) break;
                }
            } else if(op==4) {
                for(int j=0;j<rate;++j) {
                    ++candidates;
                    if(accepted<256) {
                        reservoir|=uint64_t(buf[j])<<bits; bits+=8;
                        while(bits>=width && accepted<256) {
                            int v=int(reservoir&((UINT64_C(1)<<width)-1));
                            put_i32(out,accepted++,GAMMA1-v); reservoir>>=width; bits-=width;
                        }
                    }
                    if(stop && accepted==256) break;
                }
            } else if(op==5) {
                int start=0;
                if(b==0) { for(int j=0;j<8;++j) signs|=uint64_t(buf[j])<<(8*j); start=8; }
                for(int j=start;j<rate;++j) {
                    int v=b<force_blocks?255:int(buf[j]); ++candidates;
                    if(accepted<uint32_t(TAU)) {
                        int i=256-TAU+int(accepted);
                        if(v<=i) { put_i32(out,i,get_i32(out,v)); put_i32(out,v,1-2*int(signs&1)); signs>>=1; ++accepted; }
                    }
                    if(stop && accepted==uint32_t(TAU)) break;
                }
            }
        }
        __syncwarp(0xffffffffu);
        const unsigned pair_done=__shfl_sync(0xffffffffu,
            unsigned(!valid || (stop && accepted==uint32_t(units))),lane&~1u);
        const bool all_done=__all_sync(0xffffffffu,pair_done);
        if(stop && all_done) break; // Identical decision for all 32 physical lanes.
    }
    if(half==0 && valid) {
        traces[req]={blocks,accepted,candidates,checksum,accepted==uint32_t(units)?0u:1u};
        work[req]={blocks,uint32_t(input_bytes/rate),executed,executed-blocks};
    }
    if(lane==0) warp_work[warp_index]={valid_pairs,16-valid_pairs,uint32_t(input_bytes/rate),executed};
}

struct Device {
    void* p=nullptr;
    explicit Device(size_t n) { CUDA_OK(cudaMalloc(&p,std::max(size_t(1),n))); }
    ~Device() { if(p) cudaFree(p); }
    Device(const Device&)=delete; Device& operator=(const Device&)=delete;
};
struct Event {
    cudaEvent_t event{}; Event(){CUDA_OK(cudaEventCreate(&event));}
    ~Event(){cudaEventDestroy(event);}
};
static std::vector<uint8_t> read_file(const std::string& path,size_t size) {
    std::ifstream in(path,std::ios::binary); if(!in) throw std::runtime_error("open input "+path);
    std::vector<uint8_t> b(size);
    if(size && !in.read(reinterpret_cast<char*>(b.data()),size)) throw std::runtime_error("short input "+path);
    char extra; if(in.read(&extra,1)) throw std::runtime_error("long input "+path);
    return b;
}
static void save_file(const std::string& path,const void* data,size_t size) {
    std::ofstream out(path,std::ios::binary); if(!out || !out.write(reinterpret_cast<const char*>(data),size)) throw std::runtime_error("write "+path);
}
static std::vector<std::string> split(const std::string& s) {
    std::vector<std::string> v; std::stringstream ss(s); std::string x;
    while(std::getline(ss,x,'\t')) v.push_back(x); return v;
}
int main(int argc,char** argv) {
  try {
    if(argc!=8) throw std::runtime_error("usage: bench batch parameter block cases.tsv output_dir warmup repeat");
    int batch=std::stoi(argv[1]),parameter=std::stoi(argv[2]),block_index=std::stoi(argv[3]);
    int warmup=std::stoi(argv[6]),repeat=std::stoi(argv[7]); std::string outdir=argv[5];
    if(batch<=0 || warmup<0 || repeat<=1 || block_index<0 || block_index>2 || parameter!=(DILITHIUM_MODE==2?44:DILITHIUM_MODE==3?65:87)) throw std::runtime_error("bad options");
    const uint64_t rc[24]={0x1,0x8082,0x800000000000808aULL,0x8000000080008000ULL,0x808b,0x80000001,0x8000000080008081ULL,0x8000000000008009ULL,0x8a,0x88,0x80008009,0x8000000a,0x8000808b,0x800000000000008bULL,0x8000000000008089ULL,0x8000000000008003ULL,0x8000000000008002ULL,0x8000000000000080ULL,0x800a,0x800000008000000aULL,0x8000000080008081ULL,0x8000000000008080ULL,0x80000001,0x8000000080008008ULL};
    const int8_t offsets[32]={0,1,62,28,27,36,44,6,55,20,3,10,43,25,39,41,45,15,21,8,18,2,61,56,14,0,0,0,0,0,0,0};
    CUDA_OK(cudaMemcpyToSymbol(keccak_f_round_constants_PTX,rc,sizeof(rc)));
    CUDA_OK(cudaMemcpyToSymbol(offset_constants_PTX,offsets,sizeof(offsets)));
    cudaDeviceProp prop{}; int ordinal=-1; CUDA_OK(cudaGetDevice(&ordinal)); CUDA_OK(cudaGetDeviceProperties(&prop,ordinal));
    std::cout<<std::setprecision(10)<<"identity,"<<parameter<<','<<batch<<','<<block_index<<','<<ordinal<<','<<prop.major<<','<<prop.minor<<',';
    for(auto b:prop.uuid.bytes) std::cout<<std::hex<<std::setw(2)<<std::setfill('0')<<int(static_cast<unsigned char>(b));
    std::cout<<std::dec<<std::setfill(' ')<<'\n';
    std::ifstream cases(argv[4]); if(!cases) throw std::runtime_error("open cases");
    std::string line; int case_index=0,total_checks=0,total_samples=0,total_work_checks=0;
    while(std::getline(cases,line)) {
      if(line.empty()) continue; auto f=split(line); if(f.size()!=15) throw std::runtime_error("case fields");
      std::string id=f[0]; int op=std::stoi(f[1]),rate=std::stoi(f[2]),ilen=std::stoi(f[3]),olen=std::stoi(f[4]),units=std::stoi(f[5]),force=std::stoi(f[6]),budget=std::stoi(f[7]),n=std::stoi(f[8]);
      bool qualify_only=std::stoi(f[9])!=0,both=std::stoi(f[10])!=0;
      if(n<=0 || n>batch || ilen<0 || ilen>(op==1?1088:200) || olen<=0 || budget<=0 || budget>16 ||
         op<0 || op>5 || (rate!=136 && rate!=168) || force<0 || force>budget ||
         (op==0 && (ilen!=200 || olen!=200 || units!=200)) ||
         (op==1 && (units!=olen || units>rate*budget)) ||
         (op>=2 && (olen!=1024 || units!=(op==5?TAU:256)))) throw std::runtime_error("case range");
      auto input=read_file(f[11],size_t(n)*ilen),expected=read_file(f[12],size_t(n)*olen);
      Device di(input.size()),dout(expected.size()),dt(size_t(n)*sizeof(Trace)),dw(size_t(n)*sizeof(Work)),dww(size_t(4*((n+63)/64))*sizeof(WarpWork));
      if(!input.empty()) CUDA_OK(cudaMemcpy(di.p,input.data(),input.size(),cudaMemcpyHostToDevice));
      int variants=both?6:3;
      for(int position=0;position<variants;++position) {
        int backend=(position/(both?2:1)+block_index+case_index)%3;
        int stop=both?((position%2+(block_index+case_index)%2)%2==0):1;
        const char* backend_name=backend==2?"split32":backend==1?"warp":"thread";
        std::string label=id+"_"+backend_name+"_"+(stop?"on":"off");
        auto et=read_file(f[13]+(stop?"_on.bin":"_off.bin"),size_t(n)*sizeof(Trace));
        const std::string work_prefix=f[14]+"_"+backend_name+"_"+(stop?"on":"off");
        auto ew=read_file(work_prefix+"_work.bin",size_t(n)*sizeof(Work));
        auto eww=backend==2?read_file(work_prefix+"_warp_work.bin",size_t(4*((n+63)/64))*sizeof(WarpWork)):std::vector<uint8_t>{};
        auto launch=[&] {
          if(backend==2) audit_split32_kernel<<<(n+63)/64,128,64*168>>>(static_cast<const uint8_t*>(di.p),static_cast<uint8_t*>(dout.p),static_cast<Trace*>(dt.p),static_cast<Work*>(dw.p),static_cast<WarpWork*>(dww.p),n,op,rate,ilen,olen,units,force,budget,stop);
          else if(backend==1) audit_kernel<1><<<(n+3)/4,dim3(32,4),4*168>>>(static_cast<const uint8_t*>(di.p),static_cast<uint8_t*>(dout.p),static_cast<Trace*>(dt.p),static_cast<Work*>(dw.p),n,op,rate,ilen,olen,units,force,budget,stop);
          else audit_kernel<0><<<(n+127)/128,128,128*168>>>(static_cast<const uint8_t*>(di.p),static_cast<uint8_t*>(dout.p),static_cast<Trace*>(dt.p),static_cast<Work*>(dw.p),n,op,rate,ilen,olen,units,force,budget,stop);
          CUDA_OK(cudaGetLastError());
        };
        std::vector<uint8_t> got(expected.size()),trace(et.size()),work(ew.size()),warp_work(eww.size());
        auto check=[&](const char* phase) {
          CUDA_OK(cudaMemcpy(got.data(),dout.p,got.size(),cudaMemcpyDeviceToHost));
          CUDA_OK(cudaMemcpy(trace.data(),dt.p,trace.size(),cudaMemcpyDeviceToHost));
          size_t bad=0,badt=0; for(size_t i=0;i<got.size();++i) bad+=got[i]!=expected[i]; for(size_t i=0;i<trace.size();++i) badt+=trace[i]!=et[i];
          std::cout<<"check,"<<id<<','<<backend<<','<<stop<<','<<phase<<','<<n<<','<<got.size()<<','<<bad<<','<<badt<<'\n'; std::cout.flush();
          if(bad || badt) {save_file(outdir+"/FAIL_"+label+"_"+phase+".bin",got.data(),got.size()); save_file(outdir+"/FAIL_"+label+"_"+phase+"_trace.bin",trace.data(),trace.size()); throw std::runtime_error("CPU oracle mismatch "+label);}
          CUDA_OK(cudaMemcpy(work.data(),dw.p,work.size(),cudaMemcpyDeviceToHost));
          if(!warp_work.empty()) CUDA_OK(cudaMemcpy(warp_work.data(),dww.p,warp_work.size(),cudaMemcpyDeviceToHost));
          size_t badw=0,badww=0; for(size_t i=0;i<work.size();++i) badw+=work[i]!=ew[i]; for(size_t i=0;i<warp_work.size();++i) badww+=warp_work[i]!=eww[i];
          std::cout<<"workcheck,"<<id<<','<<backend<<','<<stop<<','<<phase<<','<<n<<','<<work.size()<<','<<badw<<','<<warp_work.size()<<','<<badww<<'\n'; std::cout.flush();
          if(badw || badww) { save_file(outdir+"/FAIL_"+label+"_"+phase+"_work.bin",work.data(),work.size()); if(!warp_work.empty()) save_file(outdir+"/FAIL_"+label+"_"+phase+"_warp_work.bin",warp_work.data(),warp_work.size()); throw std::runtime_error("physical work mismatch "+label); }
          ++total_work_checks; ++total_checks;
        };
        launch(); CUDA_OK(cudaDeviceSynchronize()); check("initial");
        if(!qualify_only) {
          for(int i=0;i<warmup;++i) launch(); CUDA_OK(cudaDeviceSynchronize());
          Event start,end;
          for(int i=0;i<repeat;++i) {
            CUDA_OK(cudaEventRecord(start.event)); launch(); CUDA_OK(cudaEventRecord(end.event)); CUDA_OK(cudaEventSynchronize(end.event));
            float ms=0; CUDA_OK(cudaEventElapsedTime(&ms,start.event,end.event));
            if(!(ms>0)) throw std::runtime_error("invalid event time");
            std::cout<<"raw,"<<id<<','<<backend<<','<<stop<<','<<i<<','<<ms<<'\n'; ++total_samples;
          }
          check("final");
        }
        save_file(outdir+"/"+label+"_trace.bin",trace.data(),trace.size());
        save_file(outdir+"/"+label+"_work.bin",work.data(),work.size());
        if(!warp_work.empty()) save_file(outdir+"/"+label+"_warp_work.bin",warp_work.data(),warp_work.size());
        if(position==0) save_file(outdir+"/"+id+"_gpu_output.bin",got.data(),got.size());
      }
      ++case_index; std::cout.flush();
    }
    CUDA_OK(cudaDeviceSynchronize()); std::cout<<"complete,"<<case_index<<','<<total_checks<<','<<total_samples<<','<<total_work_checks<<",PASS\n";
    return 0;
  } catch(const std::exception& e) {std::cerr<<"AUDIT_ERROR "<<e.what()<<'\n'; return 1;}
}
