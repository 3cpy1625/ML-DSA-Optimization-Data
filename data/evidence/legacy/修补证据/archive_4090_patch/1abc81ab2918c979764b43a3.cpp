#include "nist_native_support_v2.hpp"
#include <iterator>
using namespace loce::pqc;
using namespace loce::bench;
using Bytes = std::vector<std::uint8_t>;

static Bytes read_bytes(const char* path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) fail("cannot read input/expected bytes");
    return Bytes(std::istreambuf_iterator<char>(f), {});
}
static void save(const std::string& path, const Bytes& bytes) {
    std::ofstream f(path, std::ios::binary);
    f.write(reinterpret_cast<const char*>(bytes.data()), bytes.size()); f.close();
    if (!f) fail("cannot save output");
}
// Only count residual bytes; do not serialize secret workspace contents.
static std::uint64_t nonzero(BufferView view) {
    Bytes chunk(std::min<std::size_t>(view.bytes, 1024 * 1024));
    std::uint64_t count = 0;
    for (std::size_t offset = 0; offset < view.bytes; offset += chunk.size()) {
        auto bytes = std::min(chunk.size(), view.bytes - offset);
        cuda_check(cudaMemcpy(chunk.data(), view.data + offset, bytes,
                              cudaMemcpyDeviceToHost), "inspect residual workspace");
        count += std::count_if(chunk.begin(), chunk.begin() + bytes, [](auto v) { return v != 0; });
        std::fill(chunk.begin(), chunk.end(), 0);
    }
    return count;
}
int main(int argc, char** argv) {
    try {
        if (argc != 8) fail("MODULE_DIR PARAM MSG_BYTES INPUT EXPECTED OUTPUT_PREFIX IDENTITY");
        const int p = std::stoi(argv[2]);
        if (p != 44 && p != 65 && p != 87) fail("wrong parameter");
        constexpr std::size_t n = 256;
        const std::size_t message_bytes = std::stoull(argv[3]);
        if (!message_bytes || message_bytes > 8192) fail("unsupported message size");
        const auto level = p == 44 ? SecurityLevel::level1 : p == 65 ? SecurityLevel::level3 : SecurityLevel::level5;
        const auto traits = parameter_traits(Algorithm::mldsa, level);
        const auto input = read_bytes(argv[4]), expected = read_bytes(argv[5]);
        if (input.size() != n * (message_bytes + traits.secret_key_bytes + 32) ||
            expected.size() != n * traits.signature_bytes) fail("wrong packed shape");
        auto arm = reinterpret_cast<void (*)(int)>(dlsym(RTLD_DEFAULT, "repair_arm"));
        auto hits = reinterpret_cast<int (*)()>(dlsym(RTLD_DEFAULT, "repair_hits"));
        if (!arm || !hits) fail("test interposer not loaded");
        arm(0);
        NativeModule module(argv[1], Algorithm::mldsa, OperationKind::sign, level);
        module.write_direct_identity(argv[7], OperationKind::sign);
        if (!module.descriptor().workspace_requirements) fail("workspace query missing");
        DeviceWorkspace workspace(module.descriptor().workspace_requirements(
            {Algorithm::mldsa, OperationKind::sign, level, n, message_bytes}), true);
        if (!workspace.valid()) fail("workspace allocation failed");
        cudaStream_t stream{};
        cuda_check(cudaStreamCreate(&stream), "create stream");
        std::vector<RequestContext> contexts(n);
        for (std::size_t i = 0; i < n; ++i) {
            contexts[i].request_id = i;
            contexts[i].algorithm = Algorithm::mldsa;
            contexts[i].operation = OperationKind::sign;
            contexts[i].level = level;
        }
        auto cv = [](const std::uint8_t* p, std::size_t bytes, std::size_t stride) {
            return ConstBufferView{p, bytes, stride, MemoryDomain::host};
        };
        Bytes output(expected.size(), 0xa5);
        OperationBatch batch{contexts.data(), n, reinterpret_cast<void*>(stream), workspace.views()};
        backend::MlDsaSignNativeArgumentsV1 args{};
        args.messages = cv(input.data(), n * message_bytes, message_bytes);
        args.secret_keys = cv(input.data() + n * message_bytes, n * traits.secret_key_bytes, traits.secret_key_bytes);
        args.randomness = cv(input.data() + n * (message_bytes + traits.secret_key_bytes), n * 32, 32);
        args.signatures = {output.data(), output.size(), traits.signature_bytes, MemoryDomain::host};
        args.message_bytes = message_bytes; args.device_resident = false;
        batch.native_arguments = &args; batch.native_arguments_size = sizeof(args);
        std::ofstream trace(std::string(argv[6]) + ".trace.jsonl");
        if (!trace) fail("cannot create trace");
        const int modes[] = {0, 1, 0, 2, 0, 3, 0};
        for (int phase = 0; phase < 7; ++phase) {
            const int mode = modes[phase];
            std::fill(output.begin(), output.end(), 0xa5);
            for (auto& ctx : contexts) ctx.completion = CompletionState::empty;
            // No workspace reset here: recovery must use the same dirty allocation.
            arm(mode);
            const auto status = module.invoke(batch);
            const int injected = hits();
            arm(0);
            const auto sync = cudaStreamSynchronize(stream);
            const auto last = cudaGetLastError();
            const auto committed = std::count_if(contexts.begin(), contexts.end(), [](const auto& c) { return c.completion == CompletionState::committed; });
            const auto failed = std::count_if(contexts.begin(), contexts.end(), [](const auto& c) { return c.completion == CompletionState::failed; });
            const bool unchanged = std::all_of(output.begin(), output.end(), [](auto x) { return x == 0xa5; });
            std::uint64_t residual[3] = {};
            if (mode && sync == cudaSuccess) {
                residual[0] = nonzero(workspace.views().primary);
                residual[1] = nonzero(workspace.views().temporary);
                residual[2] = nonzero(workspace.views().auxiliary);
            }
            trace << "{\"phase\":" << phase << ",\"fault_mode\":" << mode
                  << ",\"injected_calls\":" << injected << ",\"status\":" << static_cast<int>(status)
                  << ",\"sync_status\":" << static_cast<int>(sync) << ",\"last_error\":" << static_cast<int>(last)
                  << ",\"committed\":" << committed << ",\"failed\":" << failed
                  << ",\"output_unchanged\":" << (unchanged ? "true" : "false")
                  << ",\"primary\":" << reinterpret_cast<std::uintptr_t>(workspace.views().primary.data)
                  << ",\"temporary\":" << reinterpret_cast<std::uintptr_t>(workspace.views().temporary.data)
                  << ",\"auxiliary\":" << reinterpret_cast<std::uintptr_t>(workspace.views().auxiliary.data)
                  << ",\"workspace_nonzero\":[" << residual[0] << ',' << residual[1] << ',' << residual[2] << "]}\n";
            trace.flush();
            if (!trace) fail("cannot save phase trace");
            if (sync != cudaSuccess || last != cudaSuccess) fail("CUDA error state did not recover");
            if (mode) {
                if (injected != 1 || status != Status::backend_error || !unchanged || committed != 0 || failed != n)
                    fail("internal fault was not isolated and propagated, phase=" + std::to_string(phase));
            } else {
                save(std::string(argv[6]) + ".phase" + std::to_string(phase), output);
                if (injected != 0 || status != Status::success || committed != n || output != expected)
                    fail("valid/recovery output differs from official answer, phase=" + std::to_string(phase));
            }
        }
        trace.close();
        module.write_direct_identity(std::string(argv[7]) + ".after", OperationKind::sign);
        // End-of-test hygiene only. This is not production automatic zeroization.
        for (auto view : {workspace.views().primary, workspace.views().temporary, workspace.views().auxiliary})
            if (view.bytes) cuda_check(cudaMemsetAsync(view.data, 0, view.bytes, stream), "test final cleanup");
        cuda_check(cudaStreamSynchronize(stream), "cleanup sync");
        cuda_check(cudaStreamDestroy(stream), "destroy stream");
        std::printf("INTERNAL_CUDA_RECOVERY_PASS parameter=%d faults=3 phases=7\n", p);
        return 0;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "INTERNAL_CUDA_RECOVERY_FAILED: %s\n", e.what()); return 1;
    }
}
