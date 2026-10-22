// Extracted verbatim from the sealed production benchmark; source SHA256 d17b1ea9ae272712c8c5f5001acdce9d13a7c74a080552389fc6216dff540e2a
#pragma once
#include <cuda_runtime.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>
#include "loce/pqc/backend/mldsa_native_arguments.hpp"
#include "loce/pqc/backend/module_abi.hpp"
#include "loce/pqc/backend/module_registry.generated.hpp"
#include "loce/pqc/parameter_traits.hpp"
#include "loce/pqc/execution/sha256.hpp"
namespace loce::bench {
using namespace loce::pqc;
[[noreturn]] void fail(const std::string& message) {
    throw std::runtime_error(message);
}

void cuda_check(cudaError_t status, const char* what) {
    if (status != cudaSuccess) {
        fail(std::string(what) + ": " + cudaGetErrorString(status));
    }
}

const char* operation_name(OperationKind operation) {
    switch (operation) {
        case OperationKind::keygen: return "keygen";
        case OperationKind::encaps: return "encaps";
        case OperationKind::decaps: return "decaps";
        case OperationKind::sign: return "sign";
        case OperationKind::verify: return "verify";
    }
    return "invalid";
}

class DeviceWorkspace final {
public:
    DeviceWorkspace() = default;
    explicit DeviceWorkspace(const WorkspaceRequirements& requirements,
                             bool pitched_rows = false) {
        const std::size_t batch = requirements.primary_stride == 0 ? 0 :
            requirements.primary_bytes / requirements.primary_stride;
        std::size_t primary_stride = requirements.primary_stride;
        std::size_t temporary_stride = requirements.temporary_stride;
        if (pitched_rows && batch != 0) {
            allocate_pitched(primary_, primary_stride,
                             requirements.primary_stride, batch);
            allocate_pitched(temporary_, temporary_stride,
                             requirements.temporary_stride, batch);
        } else {
            allocate(primary_, requirements.primary_bytes);
            allocate(temporary_, requirements.temporary_bytes);
        }
        allocate(auxiliary_, requirements.auxiliary_bytes);
        views_.primary = {primary_, batch * primary_stride,
                          primary_stride, MemoryDomain::device, 256};
        views_.temporary = {temporary_, batch * temporary_stride,
                            temporary_stride, MemoryDomain::device, 256};
        const std::size_t auxiliary_stride = batch == 0 ? 0 :
            requirements.auxiliary_bytes / batch;
        views_.auxiliary = {auxiliary_, requirements.auxiliary_bytes, auxiliary_stride,
                            MemoryDomain::device, 256};
    }
    ~DeviceWorkspace() {
        cudaFree(primary_);
        cudaFree(temporary_);
        cudaFree(auxiliary_);
    }
    DeviceWorkspace(DeviceWorkspace&& other) noexcept { *this = std::move(other); }
    DeviceWorkspace& operator=(DeviceWorkspace&& other) noexcept {
        if (this == &other) return *this;
        cudaFree(primary_); cudaFree(temporary_); cudaFree(auxiliary_);
        primary_ = std::exchange(other.primary_, nullptr);
        temporary_ = std::exchange(other.temporary_, nullptr);
        auxiliary_ = std::exchange(other.auxiliary_, nullptr);
        views_ = other.views_;
        valid_ = other.valid_;
        return *this;
    }
    DeviceWorkspace(const DeviceWorkspace&) = delete;
    DeviceWorkspace& operator=(const DeviceWorkspace&) = delete;
    [[nodiscard]] bool valid() const noexcept { return valid_; }
    [[nodiscard]] OperationWorkspace views() const noexcept { return views_; }
private:
    void allocate(std::uint8_t*& pointer, std::size_t bytes) {
        if (bytes != 0 && cudaMalloc(&pointer, bytes) != cudaSuccess) valid_ = false;
    }
    void allocate_pitched(std::uint8_t*& pointer, std::size_t& pitch,
                          std::size_t width, std::size_t height) {
        if (width != 0 && height != 0 &&
            cudaMallocPitch(&pointer, &pitch, width, height) != cudaSuccess) {
            valid_ = false;
        }
    }
    std::uint8_t* primary_{};
    std::uint8_t* temporary_{};
    std::uint8_t* auxiliary_{};
    OperationWorkspace views_{};
    bool valid_{true};
};

std::string direct_hex_digest(
    const execution::detail::Sha256::Digest& digest) {
    constexpr char digits[] = "0123456789abcdef";
    std::string result(digest.size() * 2, '0');
    for (std::size_t index = 0; index < digest.size(); ++index) {
        result[2 * index] = digits[digest[index] >> 4U];
        result[2 * index + 1] = digits[digest[index] & 0x0fU];
    }
    return result;
}

std::string direct_sha256_fd(int descriptor) {
    if (descriptor < 0 || lseek(descriptor, 0, SEEK_SET) < 0) return {};
    execution::detail::Sha256 hash;
    std::array<std::uint8_t, 64 * 1024> buffer{};
    for (;;) {
        const auto bytes = read(descriptor, buffer.data(), buffer.size());
        if (bytes < 0) return {};
        if (bytes == 0) break;
        hash.update(buffer.data(), static_cast<std::size_t>(bytes));
    }
    return direct_hex_digest(hash.finish());
}

class NativeModule final {
public:
    NativeModule(const std::filesystem::path& directory, Algorithm algorithm,
                 OperationKind operation, SecurityLevel level) {
#ifdef LOCE_STATIC_NATIVE_FACTORY
        (void)directory;
        module_ = loce_pqc_native_module_v1();
#else
        const auto operation_mask = [&] {
            switch (operation) {
                case OperationKind::keygen: return backend::module_operation_keygen;
                case OperationKind::encaps: return backend::module_operation_encaps;
                case OperationKind::decaps: return backend::module_operation_decaps;
                case OperationKind::sign: return backend::module_operation_sign;
                case OperationKind::verify: return backend::module_operation_verify;
            }
            return std::uint32_t{0};
        }();
        std::string filename;
        for (const auto& binding : backend::module_registry) {
            if (binding.algorithm == algorithm && binding.level == level &&
                (binding.operation_mask & operation_mask) != 0) {
                if (!filename.empty()) fail("duplicate operation module binding");
                filename = binding.filename;
            }
        }
        if (filename.empty()) fail("operation module binding missing");
        const auto path = std::filesystem::canonical(directory / filename);
        const int descriptor = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
        if (descriptor < 0) fail("native module open failed");
        struct stat before{};
        if (fstat(descriptor, &before) != 0 || !S_ISREG(before.st_mode)) {
            close(descriptor);
            fail("native module file identity failed");
        }
        const auto pre_hash = direct_sha256_fd(descriptor);
        if (pre_hash.empty()) {
            close(descriptor);
            fail("native module pre-load hash failed");
        }
        const std::string descriptor_path =
            "/proc/self/fd/" + std::to_string(descriptor);
        handle_ = dlopen(descriptor_path.c_str(), RTLD_NOW | RTLD_LOCAL);
        if (handle_ == nullptr) fail(std::string("dlopen failed: ") + dlerror());
        using Factory = backend::NativeModuleV1 (*)() noexcept;
        void* symbol = dlsym(handle_, "loce_pqc_native_module_v1");
        if (symbol == nullptr) fail("native module factory not found");
        Factory factory{};
        static_assert(sizeof(factory) == sizeof(symbol));
        std::memcpy(&factory, &symbol, sizeof(factory));
        module_ = factory();
        struct stat after{};
        struct stat path_after{};
        const auto post_hash = direct_sha256_fd(descriptor);
        const bool stable = fstat(descriptor, &after) == 0 &&
            before.st_dev == after.st_dev && before.st_ino == after.st_ino &&
            pre_hash == post_hash && lstat(path.c_str(), &path_after) == 0 &&
            S_ISREG(path_after.st_mode) && before.st_dev == path_after.st_dev &&
            before.st_ino == path_after.st_ino;
        if (!stable) {
            close(descriptor);
            fail("native module changed during load");
        }
        descriptor_ = descriptor;
        loaded_path_ = path.string();
        pre_load_sha256_ = pre_hash;
        post_load_sha256_ = post_hash;
        loaded_device_ = static_cast<std::uint64_t>(before.st_dev);
        loaded_inode_ = static_cast<std::uint64_t>(before.st_ino);
        expected_filename_ = filename;
#endif
        invoke_ = backend::select(module_, operation);
        if (module_.abi_version != backend::native_module_abi_v1 ||
            module_.algorithm != algorithm || module_.level != level ||
            invoke_ == nullptr) fail("native module identity mismatch");
    }
    ~NativeModule() {
        if (handle_ != nullptr) dlclose(handle_);
        if (descriptor_ >= 0) close(descriptor_);
    }
    NativeModule(const NativeModule&) = delete;
    NativeModule& operator=(const NativeModule&) = delete;
    Status invoke(OperationBatch batch) const { return invoke_(batch); }
    [[nodiscard]] const backend::NativeModuleV1& descriptor() const noexcept {
        return module_;
    }
    void write_direct_identity(const std::filesystem::path& output_path,
                               OperationKind operation) const {
#ifdef LOCE_STATIC_NATIVE_FACTORY
        (void)output_path;
        (void)operation;
        fail("static native factory has no dynamic loaded identity");
#else
        const auto* identity = module_.identity;
        if (identity == nullptr || identity->abi_version !=
                backend::native_module_abi_v1) {
            fail("native module embedded identity missing");
        }
        int ordinal = -1;
        cudaDeviceProp properties{};
        cuda_check(cudaGetDevice(&ordinal), "cudaGetDevice(identity)");
        cuda_check(cudaGetDeviceProperties(&properties, ordinal),
                   "cudaGetDeviceProperties(identity)");
        constexpr char digits[] = "0123456789abcdef";
        std::string uuid(32, '0');
        for (std::size_t index = 0; index < 16; ++index) {
            const auto byte = static_cast<unsigned char>(properties.uuid.bytes[index]);
            uuid[2 * index] = digits[byte >> 4U];
            uuid[2 * index + 1] = digits[byte & 0x0fU];
        }
        std::ofstream output(output_path, std::ios::trunc);
        if (!output) fail("native-direct identity output open failed");
        output << "{\n"
               << "  \"schema\": \"loce.native-direct-loaded-identity.v1\",\n"
               << "  \"expected_filename\": \"" << expected_filename_ << "\",\n"
               << "  \"loaded_path\": \"" << loaded_path_ << "\",\n"
               << "  \"pre_load_sha256\": \"" << pre_load_sha256_ << "\",\n"
               << "  \"post_load_sha256\": \"" << post_load_sha256_ << "\",\n"
               << "  \"device\": " << loaded_device_ << ",\n"
               << "  \"inode\": " << loaded_inode_ << ",\n"
               << "  \"resolved_symbol\": \"loce_pqc_native_module_v1\",\n"
               << "  \"algorithm\": \""
               << (module_.algorithm == Algorithm::mlkem ? "ML-KEM" : "ML-DSA")
               << "\",\n  \"level\": " << static_cast<unsigned>(module_.level)
               << ",\n  \"operation\": \"" << operation_name(operation) << "\",\n"
               << "  \"module_name\": \"" << (module_.module_name ? module_.module_name : "") << "\",\n"
               << "  \"module_build_identity\": \"" << (module_.source_identity ? module_.source_identity : "") << "\",\n"
               << "  \"embedded\": {\"module_id\": \"" << (identity->module_id ? identity->module_id : "")
               << "\", \"compilation_input_sha256\": \"" << (identity->compilation_input_sha256 ? identity->compilation_input_sha256 : "")
               << "\", \"build_provenance_sha256\": \"" << (identity->build_provenance_sha256 ? identity->build_provenance_sha256 : "")
               << "\", \"execution_contract_registry_sha256\": \"" << (identity->execution_contract_registry_sha256 ? identity->execution_contract_registry_sha256 : "")
               << "\", \"policy_registry_sha256\": \"" << (identity->policy_registry_sha256 ? identity->policy_registry_sha256 : "")
               << "\", \"build_id\": \"" << (identity->build_id ? identity->build_id : "")
               << "\", \"release_family_id\": \"" << (identity->release_family_id ? identity->release_family_id : "")
               << "\", \"algorithm\": \"" << (identity->algorithm ? identity->algorithm : "")
               << "\", \"parameter_set\": \"" << (identity->parameter_set ? identity->parameter_set : "")
               << "\", \"operation_mask\": " << identity->operation_mask
               << ", \"policy_id\": \"" << (identity->policy_id ? identity->policy_id : "")
               << "\", \"sm_arch\": \"" << (identity->sm_arch ? identity->sm_arch : "") << "\"},\n"
               << "  \"cuda_device\": {\"ordinal\": " << ordinal
               << ", \"uuid\": \"" << uuid
               << "\", \"compute_capability_major\": " << properties.major
               << ", \"compute_capability_minor\": " << properties.minor << "}\n}\n";
        if (!output) fail("native-direct identity output write failed");
#endif
    }
private:
    void* handle_{};
    backend::NativeModuleV1 module_{};
    backend::NativeInvoke invoke_{};
    std::string loaded_path_{};
    std::string pre_load_sha256_{};
    std::string post_load_sha256_{};
    std::string expected_filename_{};
    std::uint64_t loaded_device_{};
    std::uint64_t loaded_inode_{};
    int descriptor_{-1};
};
}
