// Test-process-only CUDA API interposition. No production binary is rewritten.
#include <cuda_runtime.h>
#include <dlfcn.h>
#include <atomic>
#include <cstdlib>

static std::atomic<int> armed{0};
static std::atomic<int> hits{0};
extern "C" void repair_arm(int mode) { hits.store(0); armed.store(mode); }
extern "C" int repair_hits() { return hits.load(); }
static bool take(int mode) {
    int wanted = mode;
    if (!armed.compare_exchange_strong(wanted, 0)) return false;
    hits.fetch_add(1);
    return true;
}
template<class T> static T real(const char* name) {
    auto p = reinterpret_cast<T>(dlsym(RTLD_NEXT, name));
    if (!p) std::abort();
    return p;
}
extern "C" cudaError_t cudaMemset2DAsync(void* ptr, size_t pitch, int value,
                                        size_t width, size_t height, cudaStream_t stream) {
    if (take(1)) return cudaErrorMemoryAllocation;
    using Fn = cudaError_t (*)(void*, size_t, int, size_t, size_t, cudaStream_t);
    return real<Fn>("cudaMemset2DAsync")(ptr, pitch, value, width, height, stream);
}
extern "C" cudaError_t cudaMemcpy2DAsync(void* dst, size_t dpitch, const void* src,
                                        size_t spitch, size_t width, size_t height,
                                        cudaMemcpyKind kind, cudaStream_t stream) {
    if (kind == cudaMemcpyHostToDevice && take(2)) return cudaErrorInvalidValue;
    if (kind == cudaMemcpyDeviceToHost && take(3)) return cudaErrorInvalidValue;
    using Fn = cudaError_t (*)(void*, size_t, const void*, size_t, size_t, size_t,
                              cudaMemcpyKind, cudaStream_t);
    return real<Fn>("cudaMemcpy2DAsync")(dst, dpitch, src, spitch, width, height, kind, stream);
}
