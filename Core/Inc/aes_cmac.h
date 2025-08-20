#ifndef AES_CMAC_H
#define AES_CMAC_H

#include <stdint.h>
#include <stddef.h>

#define AES_BLOCK_SIZE 16  // 128位AES块大小
#define Rb 0x87            // CMAC子密钥生成常量

// AES-CMAC上下文结构体
typedef struct {
    uint8_t key[AES_BLOCK_SIZE];  // 128位密钥
} AES_CMAC_CTX;

// 函数声明
void aes_cmac_init(AES_CMAC_CTX *ctx, const uint8_t *key);
void aes_cmac_compute(AES_CMAC_CTX *ctx, const uint8_t *msg, uint32_t msg_len, uint8_t *out_mac);
void aes_cmac_test(void);         // 测试函数
void aes_test(void);              // AES单独测试函数

#endif  // AES_CMAC_H