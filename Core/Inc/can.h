/* USER CODE BEGIN Header */
/* USER CODE END Header */
/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __CAN_H__
#define __CAN_H__

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* USER CODE BEGIN Includes */
/* USER CODE END Includes */

extern CAN_HandleTypeDef hcan;

/* USER CODE BEGIN Private defines */
/* USER CODE END Private defines */

void MX_CAN_Init(void);

/* USER CODE BEGIN Prototypes */
void CAN_Filter_Config(void);
uint8_t CAN_Send_Message(uint32_t id, uint8_t *data, uint8_t len);
uint8_t CAN_Receive_Message(uint32_t *id, uint8_t *data, uint8_t *len);

/* USER CODE END Prototypes */



#ifdef __cplusplus
}
#endif

#endif /* __CAN_H__ */

